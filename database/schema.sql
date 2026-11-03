-- MySQL 8.4: execute on an explicitly selected tourism_recommender database.
-- CREATE DATABASE and account provisioning require separate administrator setup.
CREATE TABLE IF NOT EXISTS dataset_batches (
  batch_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  contract_version VARCHAR(16) NOT NULL,
  standard_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  manifest_json JSON NOT NULL,
  dictionaries_json JSON NOT NULL,
  sources_json JSON NOT NULL,
  state VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (batch_id),
  CHECK (state IN ('loading', 'ready', 'failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS attractions (
  batch_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  attraction_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(512) NOT NULL,
  country_code CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  province_key VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  province_name VARCHAR(128) NULL,
  city_key VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  city_name VARCHAR(128) NULL,
  grade_system VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  grade_status VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  grade_level VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  type_codes JSON NOT NULL,
  price_form VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  price_min DECIMAL(12,2) NULL,
  price_max DECIMAL(12,2) NULL,
  currency CHAR(3) CHARACTER SET ascii COLLATE ascii_bin NULL,
  price_basis TEXT NULL,
  price_policy_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  price_raw TEXT NULL,
  source_refs JSON NOT NULL,
  collected_at DATETIME(6) NOT NULL,
  PRIMARY KEY (batch_id, attraction_id),
  KEY idx_attractions_province (batch_id, country_code, province_key),
  KEY idx_attractions_city (batch_id, country_code, city_key),
  KEY idx_attractions_grade (batch_id, country_code, grade_system, grade_status, grade_level),
  KEY idx_attractions_price (batch_id, currency, price_policy_id, price_form, price_min),
  CONSTRAINT fk_attractions_batch FOREIGN KEY (batch_id) REFERENCES dataset_batches(batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS source_records (
  batch_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  source_ref VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  source_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  source_item_id TEXT NULL,
  source_url TEXT NOT NULL,
  collected_at DATETIME(6) NOT NULL,
  source_date VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NULL,
  source_date_kind VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  raw_ref TEXT NOT NULL,
  payload_json JSON NOT NULL,
  PRIMARY KEY (batch_id, source_ref),
  CONSTRAINT fk_sources_batch FOREIGN KEY (batch_id) REFERENCES dataset_batches(batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS analysis_results (
  batch_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  engine VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  metric VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  dimension_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  dimensions_json JSON NOT NULL,
  status VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  value_json JSON NULL,
  PRIMARY KEY (batch_id, engine, metric, dimension_key),
  CONSTRAINT fk_analysis_batch FOREIGN KEY (batch_id) REFERENCES dataset_batches(batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
