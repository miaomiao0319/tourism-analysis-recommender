"""Read-only attraction queries; all operations require an explicitly ready batch.

The caller supplies a connection factory so credentials stay in application config.
Statistics and the public error adapter are separate integration tasks.
"""
import json
import re
from decimal import Decimal, InvalidOperation

from cleaning.atlas_clean import FIELDS

LIST_FILTERS = {'q', 'country_code', 'province_key', 'city_key', 'grade_system', 'grade_status', 'grade_level', 'type_code', 'max_price', 'currency', 'price_policy_id'}


def decoded(value):
    return json.loads(value) if isinstance(value, (str, bytes, bytearray)) else value


def validate_syntax(batch_id, filters):
    if not isinstance(batch_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', batch_id):
        raise ValueError('INVALID_PARAMETER')
    if not isinstance(filters, dict):
        raise ValueError('INVALID_PARAMETER')
    for key, value in filters.items():
        if value is not None and (not isinstance(value, str) or (not value and key != 'q')):
            raise ValueError('INVALID_PARAMETER')
    for key, pattern in (('country_code', r'[A-Z]{2}'), ('currency', r'[A-Z]{3}'),
                         ('price_policy_id', r'[A-Za-z0-9_-]{1,64}'),
                         ('province_key', r'[A-Za-z0-9_:-]{1,64}'), ('city_key', r'[A-Za-z0-9_:-]{1,64}')):
        if filters.get(key) is not None and not re.fullmatch(pattern, filters[key]):
            raise ValueError('INVALID_PARAMETER')
    raw = filters.get('max_price')
    if raw is not None and not re.fullmatch(r'(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?', raw):
        raise ValueError('INVALID_PARAMETER')
    if filters.get('q') is not None and len(filters['q'].strip()) > 100:
        raise ValueError('INVALID_PARAMETER')


def validate_dimensions(cursor, batch_id, filters, dictionaries):
    regions = {r['key']: r for r in dictionaries['regions']}
    province, city, country = (filters.get(k) for k in ('province_key', 'city_key', 'country_code'))
    for key, level in ((province, 'province'), (city, 'city')):
        if key is not None and (key not in regions or regions[key]['level'] != level or (country and regions[key]['country_code'] != country)):
            raise ValueError('INVALID_FILTER')
    if province and city and regions[city]['parent_key'] != province:
        raise ValueError('INVALID_FILTER')
    if country:
        cursor.execute('SELECT DISTINCT country_code FROM attractions WHERE batch_id=%s AND country_code=%s', (batch_id, country))
        if cursor.fetchone() is None:
            raise ValueError('INVALID_FILTER')
    type_code = filters.get('type_code')
    if type_code is not None and type_code not in {t['code'] for t in dictionaries['types']}:
        raise ValueError('INVALID_FILTER')
    system, status, level = (filters.get(x) for x in ('grade_system', 'grade_status', 'grade_level'))
    systems = {s['code']: s for s in dictionaries['grade_systems']}
    if system and system != 'UNKNOWN' and system not in systems:
        raise ValueError('INVALID_FILTER')
    if status and status not in ('rated', 'unrated', 'unknown', 'conflict'):
        raise ValueError('INVALID_FILTER')
    if status in ('unknown', 'conflict') and (level or (system and system != 'UNKNOWN')):
        raise ValueError('INVALID_FILTER')
    if system == 'UNKNOWN' and status in ('rated', 'unrated'):
        raise ValueError('INVALID_FILTER')
    if level:
        if not system or system == 'UNKNOWN' or level not in systems[system]['levels'] or status not in (None, 'rated'):
            raise ValueError('INVALID_FILTER')
        return dict(filters, grade_status='rated')
    return filters


def attraction(row):
    item = dict(zip(FIELDS, row))
    for key in ('type_codes', 'source_refs'):
        item[key] = decoded(item[key])
    for key in ('price_min', 'price_max'):
        if item[key] is not None:
            item[key] = format(item[key], '.2f')
    item['collected_at'] = item['collected_at'].isoformat(timespec='microseconds') + 'Z'
    return item


def predicates(batch_id, filters, sort, policies):
    if set(filters) - LIST_FILTERS:
        raise ValueError('INVALID_PARAMETER')
    if sort not in ('name_asc', 'price_asc', 'price_desc'):
        raise ValueError('INVALID_PARAMETER')
    where, args = ['batch_id=%s'], [batch_id]
    for key in ('country_code', 'province_key', 'city_key', 'grade_system', 'grade_status', 'grade_level'):
        if filters.get(key) is not None:
            where.append(key + '=%s'); args.append(filters[key])
    if filters.get('q'):
        query = filters['q'].strip()
        if len(query) > 100:
            raise ValueError('INVALID_PARAMETER')
        where.append("name LIKE %s ESCAPE '!'")
        args.append('%' + query.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%')
    if filters.get('type_code') is not None:
        where.append('JSON_CONTAINS(type_codes, %s)')
        args.append(json.dumps(filters['type_code'], ensure_ascii=False))
    price_context = filters.get('max_price') is not None or sort != 'name_asc'
    currency, policy = filters.get('currency'), filters.get('price_policy_id')
    if price_context:
        if not policies:
            raise ValueError('PRICE_POLICY_NOT_READY')
        if not any(p['id'] == policy and p['currency'] == currency for p in policies):
            raise ValueError('INVALID_FILTER')
        where.extend(["price_form IN ('free','exact')", 'price_min=price_max', 'currency=%s', 'price_policy_id=%s'])
        args.extend([currency, policy])
        if filters.get('max_price') is not None:
            try:
                raw = filters['max_price']
                if not isinstance(raw, str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?', raw):
                    raise ValueError('INVALID_PARAMETER')
                amount = Decimal(raw)
            except (InvalidOperation, TypeError) as error:
                raise ValueError('INVALID_PARAMETER') from error
            where.append('price_min<=%s'); args.append(amount)
    elif currency is not None or policy is not None:
        raise ValueError('INVALID_PARAMETER')
    order = {'name_asc': 'name ASC, attraction_id ASC', 'price_asc': 'price_min ASC, attraction_id ASC', 'price_desc': 'price_min DESC, attraction_id ASC'}[sort]
    return ' AND '.join(where), args, order


class AttractionRepository:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    @staticmethod
    def _ready(cursor, batch_id):
        cursor.execute('SELECT state,contract_version,dictionaries_json FROM dataset_batches WHERE batch_id=%s', (batch_id,))
        row = cursor.fetchone()
        if row is None or row[0] != 'ready':
            raise ValueError('DATASET_NOT_READY')
        if row[1] != '1.0':
            raise ValueError('DATASET_INVALID')
        dictionaries = decoded(row[2])
        if not isinstance(dictionaries, dict) or any(not isinstance(dictionaries.get(k), list) for k in ('regions','types','grade_systems','price_policies')):
            raise ValueError('DATASET_INVALID')
        return dictionaries

    def load_dataset(self, batch_id):
        validate_syntax(batch_id, {})
        connection = self.connection_factory()
        try:
            with connection.cursor() as cursor:
                dictionaries = self._ready(cursor, batch_id)
                cursor.execute('SELECT manifest_json,sources_json FROM dataset_batches WHERE batch_id=%s', (batch_id,))
                manifest, sources = (decoded(v) for v in cursor.fetchone())
                dictionaries = dict(dictionaries)
                dictionaries['price_policies'] = [{k: v for k, v in policy.items() if k in ('id','currency','ticket_basis','eligibility_rule')} for policy in dictionaries['price_policies']]
                dictionaries['regions'] = [dict(r, map_code=r.get('map_code'), map_resource=r.get('map_resource')) for r in dictionaries['regions']]
                public_sources = [{k: source[k] for k in ('source_id','name','base_url','coverage','collection_basis','redistribution_status','notes')} for source in sources]
                cursor.execute('SELECT DISTINCT country_code FROM attractions WHERE batch_id=%s ORDER BY country_code', (batch_id,))
                countries = [row[0] for row in cursor.fetchall()]
                cursor.execute("SELECT metric,dimensions_json FROM analysis_results WHERE batch_id=%s AND engine='spark_sql'", (batch_id,))
                available = set()
                for metric, dimensions in cursor.fetchall():
                    dimension = decoded(dimensions)
                    available.add((metric, dimension.get('scope'), dimension.get('currency'), dimension.get('price_policy_id')))
                metrics = [dict(zip(('metric','scope','currency','price_policy_id'), row)) for row in sorted(available, key=lambda r: tuple(v or '' for v in r))]
                quality = {k: v for k, v in manifest['quality'].items() if k.endswith('_count') or k in ('notes','province_counts','grade_status_counts')}
                info = dict(data_cutoff_month=manifest['data_cutoff_month'], created_at=manifest['created_at'], standard_count=manifest['standard_count'],
                    countries=countries, quality=quality, sources=public_sources, dictionaries=dictionaries, available_statistics=metrics)
                return dict(meta=dict(batch_id=batch_id, data_kind=manifest['data_kind'], contract_version=manifest['contract_version']), info=info)
        finally:
            connection.close()

    def list_statistics(self, batch_id, query, page=1, page_size=20, sort='key_asc'):
        scopes = {'attraction_count': {'all': (), 'province': ('country_code','province_key'), 'city': ('country_code','city_key'),
                    'grade': ('country_code','grade_system','grade_status','grade_level'),
                    'city_grade': ('country_code','city_key','grade_system','grade_status','grade_level'), 'type': ('country_code','type_code')},
                  'data_quality': {'all': ()},
                  'price_summary': {'all': (), 'city': ('country_code','city_key'), 'grade': ('country_code','grade_system','grade_status','grade_level')},
                  'price_histogram': {'all': (), 'city': ('country_code','city_key'), 'grade': ('country_code','grade_system','grade_status','grade_level')}}
        if not isinstance(query, dict) or set(query) - {'metric', 'scope', 'filters'}:
            raise ValueError('INVALID_PARAMETER')
        metric, scope, filters = query.get('metric'), query.get('scope', 'all'), query.get('filters', {})
        validate_syntax(batch_id, filters)
        if metric not in scopes or scope not in scopes[metric] or type(page) is not int or type(page_size) is not int or not 1 <= page <= 2147483647 or not 1 <= page_size <= 100:
            raise ValueError('INVALID_PARAMETER')
        is_price = metric in ('price_summary', 'price_histogram')
        allowed = set(scopes[metric][scope]) | ({'currency','price_policy_id'} if is_price else set())
        if set(filters) - allowed or sort not in (('key_asc','count_desc') if metric == 'attraction_count' else ('key_asc',)):
            raise ValueError('INVALID_FILTER')
        connection = self.connection_factory()
        try:
            with connection.cursor() as cursor:
                dictionary = self._ready(cursor, batch_id)
                filters = validate_dimensions(cursor, batch_id, filters, dictionary)
                if is_price:
                    currency, policy = filters.get('currency'), filters.get('price_policy_id')
                    policies = dictionary['price_policies']
                    if policies and not any(p['id'] == policy and p['currency'] == currency for p in policies):
                        raise ValueError('INVALID_FILTER')
                    if not policies and (currency is not None or policy is not None or scope != 'all'):
                        raise ValueError('PRICE_POLICY_NOT_READY')
                base = "batch_id=%s AND engine='spark_sql' AND metric=%s AND JSON_UNQUOTE(JSON_EXTRACT(dimensions_json, '$.scope'))=%s"
                args = [batch_id, metric, scope]
                if is_price and filters.get('price_policy_id') is not None:
                    base += " AND JSON_UNQUOTE(JSON_EXTRACT(dimensions_json, '$.currency'))=%s AND JSON_UNQUOTE(JSON_EXTRACT(dimensions_json, '$.price_policy_id'))=%s"
                    args += [filters['currency'], filters['price_policy_id']]
                cursor.execute('SELECT COUNT(*) FROM analysis_results WHERE ' + base, args)
                if cursor.fetchone()[0] == 0:
                    raise ValueError('STATISTIC_NOT_AVAILABLE')
                where = base
                for key, value in filters.items():
                    if key not in ('currency','price_policy_id') and value is not None:
                        where += " AND JSON_UNQUOTE(JSON_EXTRACT(dimensions_json, '$." + key + "'))=%s"
                        args.append(value)
                cursor.execute('SELECT COUNT(*) FROM analysis_results WHERE ' + where, args)
                total = cursor.fetchone()[0]
                order = "CAST(JSON_UNQUOTE(JSON_EXTRACT(value_json, '$.count')) AS UNSIGNED) DESC, dimension_key ASC" if sort == 'count_desc' else 'dimension_key ASC'
                cursor.execute('SELECT batch_id,engine,metric,dimensions_json,status,value_json FROM analysis_results WHERE ' + where + ' ORDER BY ' + order + ' LIMIT %s OFFSET %s', args + [page_size, (page-1)*page_size])
                items = [dict(batch_id=r[0], engine=r[1], metric=r[2], dimensions=decoded(r[3]), status=r[4], value=decoded(r[5])) for r in cursor.fetchall()]
                return dict(items=items, page=page, page_size=page_size, total=total, total_pages=(total + page_size - 1) // page_size)
        finally:
            connection.close()

    def list_attractions(self, batch_id, filters, page=1, page_size=20, sort='name_asc'):
        validate_syntax(batch_id, filters)
        if set(filters) - LIST_FILTERS or sort not in ('name_asc', 'price_asc', 'price_desc'):
            raise ValueError('INVALID_PARAMETER')
        if type(page) is not int or type(page_size) is not int or not 1 <= page <= 2147483647 or not 1 <= page_size <= 100:
            raise ValueError('INVALID_PARAMETER')
        connection = self.connection_factory()
        try:
            with connection.cursor() as cursor:
                dictionaries = self._ready(cursor, batch_id)
                filters = validate_dimensions(cursor, batch_id, filters, dictionaries)
                where, args, order = predicates(batch_id, filters, sort, dictionaries['price_policies'])
                cursor.execute('SELECT COUNT(*) FROM attractions WHERE ' + where, args)
                total = cursor.fetchone()[0]
                cursor.execute('SELECT ' + ','.join(FIELDS) + ' FROM attractions WHERE ' + where + ' ORDER BY ' + order + ' LIMIT %s OFFSET %s', args + [page_size, (page-1)*page_size])
                items = [attraction(row) for row in cursor.fetchall()]
            return dict(items=items, page=page, page_size=page_size, total=total, total_pages=(total + page_size - 1) // page_size)
        finally:
            connection.close()

    def get_attraction(self, batch_id, attraction_id):
        validate_syntax(batch_id, {})
        if not isinstance(attraction_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', attraction_id):
            raise ValueError('INVALID_PARAMETER')
        connection = self.connection_factory()
        try:
            with connection.cursor() as cursor:
                self._ready(cursor, batch_id)
                cursor.execute('SELECT ' + ','.join(FIELDS) + ' FROM attractions WHERE batch_id=%s AND attraction_id=%s', (batch_id, attraction_id))
                row = cursor.fetchone()
                if row is None:
                    return None
                item = attraction(row)
                refs = sorted({ref for values in item['source_refs'].values() for ref in values})
                if not refs:
                    raise ValueError('DATASET_INVALID')
                cursor.execute('SELECT source_ref,source_id,source_url,collected_at,source_date,source_date_kind FROM source_records WHERE batch_id=%s AND source_ref IN (' + ','.join(['%s']*len(refs)) + ') ORDER BY source_ref', [batch_id, *refs])
                evidence = [dict(zip(('source_ref','source_id','source_url','collected_at','source_date','source_date_kind'), values)) for values in cursor.fetchall()]
                if len(evidence) != len(refs):
                    raise ValueError('DATASET_INVALID')
                for entry in evidence:
                    entry['collected_at'] = entry['collected_at'].isoformat(timespec='microseconds') + 'Z'
                return dict(attraction=item, evidence=evidence)
        finally:
            connection.close()

    def iter_recommendation_candidates(self, batch_id, preferences):
        # B applies every hard preference; do not truncate or narrow on an unverified field.
        if not isinstance(preferences, dict):
            raise ValueError('INVALID_PARAMETER')
        region_filters = {key: preferences[key] for key in ('country_code', 'province_key', 'city_key') if preferences.get(key) is not None}
        validate_syntax(batch_id, region_filters)
        connection = self.connection_factory()
        try:
            with connection.cursor() as cursor:
                dictionaries = self._ready(cursor, batch_id)
                validate_dimensions(cursor, batch_id, region_filters, dictionaries)
                where, args, order = predicates(batch_id, region_filters, 'name_asc', dictionaries['price_policies'])
                cursor.execute('SELECT ' + ','.join(FIELDS) + ' FROM attractions WHERE ' + where + ' ORDER BY ' + order, args)
                while True:
                    rows = cursor.fetchmany(500)
                    if not rows:
                        break
                    for row in rows:
                        yield attraction(row)
        finally:
            connection.close()
