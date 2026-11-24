<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'

const { client } = defineProps({ client: { type: Object, required: true } })
const info = ref(null), meta = ref(null), result = ref(null)
const region = ref(''), interest = ref(''), budget = ref('70'), mode = ref('balanced'), policy = ref('')
const note = ref(''), busy = ref(false), datasetError = ref(''), searchError = ref('')
const detailRecord = ref(null), detailError = ref(''), detailBusy = ref(false)
const dialog = ref(null), panel = ref(''), budgetInput = ref(null)
const modes = { balanced: '均衡推荐', economy: '经济优先', interest: '兴趣优先', quality: '景区等级优先' }
const dict = computed(() => info.value?.dictionaries || {})
const policies = computed(() => dict.value.price_policies || [])
const currentPolicy = computed(() => policies.value.find(p => p.id === policy.value))
const provinces = computed(() => (dict.value.regions || []).filter(r => r.level === 'province'))
const regionGroups = computed(() => {
  const children = new Map()
  for (const r of dict.value.regions || []) {
    if (r.level !== 'city') continue
    if (!children.has(r.parent_key)) children.set(r.parent_key, [])
    children.get(r.parent_key).push(r)
  }
  const groups = provinces.value.map(p => ({ name: p.name, values: [p, ...(children.get(p.key) || [])] }))
  const parents = new Set(provinces.value.map(p => p.key))
  for (const [parent, cities] of children) if (!parents.has(parent)) groups.push({ name: '其他城市', values: cities })
  return groups
})
const test = computed(() => meta.value?.data_kind === 'test')
const month = computed(() => info.value?.data_cutoff_month?.replace('-', ' 年 ') + ' 月')
let requestId = 0, detailId = 0

function message(error) {
  return error.code ? error.message : '暂时无法连接服务，请稍后再试。'
}
const errorHelp = {
  DATASET_NOT_READY: '尚未接入可用批次，请检查 ACTIVE_BATCH_ID 后重试。',
  DEPENDENCY_UNAVAILABLE: '暂时无法读取数据库，请检查只读连接后重试。',
  DATASET_INVALID: '当前批次的数据校验未通过，请联系数据维护同学。',
}
function resetResult() {
  requestId++
  result.value = null
  searchError.value = ''
  busy.value = false
}
watch([region, interest, budget, policy, mode], () => { resetResult(); note.value = '' }, { flush: 'sync' })

async function loadDataset(refresh = false) {
  detailId++
  resetResult()
  if (dialog.value?.open) dialog.value.close()
  const previousPolicy = policy.value
  const hadData = !!info.value
  info.value = null
  meta.value = null
  datasetError.value = ''
  let dataset
  try { dataset = await client.dataset() }
  catch (error) { datasetError.value = errorHelp[error.code] || message(error); return }
  info.value = dataset.data
  meta.value = dataset.meta
  const choices = policies.value
  if (previousPolicy && choices.some(p => p.id === previousPolicy)) policy.value = previousPolicy
  else policy.value = choices.length === 1 ? choices[0].id : ''
  if (!refresh && !hadData && !choices.length) budget.value = ''
  if (refresh) {
    if ((region.value && !dict.value.regions.some(r => r.key === region.value)) ||
        (interest.value && !dict.value.types.some(t => t.code === interest.value)) ||
        (budget.value !== '' && policy.value !== previousPolicy)) {
      region.value = ''; interest.value = ''; policy.value = ''; budget.value = ''
      note.value = '批次已更新，原筛选项有变化，请重新选择偏好。'
      return
    }
    note.value = '数据批次已更新，已重新读取。'
  }
  if (region.value || interest.value || (budget.value !== '' && currentPolicy.value)) await submit(false)
}

async function submit(retry = true) {
  resetResult()
  if (!meta.value) return
  const row = dict.value.regions.find(r => r.key === region.value)
  const prefs = { batch_id: meta.value.batch_id, mode: mode.value, type_codes: interest.value ? [interest.value] : [] }
  if (row) prefs[row.level === 'city' ? 'city_key' : 'province_key'] = row.key
  if (budget.value !== '') {
    if (!/^(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?$/.test(budget.value)) {
      searchError.value = '预算请输入非负金额，最多保留两位小数。'; return
    }
    if (!currentPolicy.value) { searchError.value = '请先选择可比的票价口径。'; return }
    prefs.budget = { amount: budget.value, currency: currentPolicy.value.currency, price_policy_id: policy.value }
  }
  if (!row && !interest.value && !prefs.budget) { searchError.value = '请至少选择地区、兴趣或单景点门票预算。'; return }
  const seq = ++requestId
  busy.value = true
  try {
    const reply = await client.recommend(prefs)
    if (seq !== requestId) return
    if (reply.meta.batch_id !== meta.value.batch_id) throw Object.assign(new Error('批次已更新。'), { code: 'BATCH_MISMATCH' })
    result.value = reply.data
  } catch (error) {
    if (seq !== requestId) return
    if (error.code === 'BATCH_MISMATCH' && retry) { await loadDataset(true); return }
    searchError.value = message(error)
  } finally { if (seq === requestId) busy.value = false }
}

async function showPanel(kind) {
  panel.value = kind
  await nextTick()
  if (!dialog.value.open) dialog.value.showModal()
}
async function showDetail(row) {
  const seq = ++detailId
  detailRecord.value = null; detailError.value = ''; detailBusy.value = true
  await showPanel('detail')
  try {
    const reply = await client.detail(row.attraction_id, meta.value.batch_id)
    if (seq === detailId) detailRecord.value = reply.data
  } catch (error) {
    if (seq !== detailId) return
    if (error.code === 'BATCH_MISMATCH') { dialog.value.close(); await loadDataset(true) }
    else detailError.value = message(error)
  } finally { if (seq === detailId) detailBusy.value = false }
}
function money(v) { return v === null || v === undefined ? '' : String(v).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1') }
function ticket(a) {
  if (a.price_form === 'conflict') return '票价资料有分歧'
  if (a.price_form === 'free') return '已确认免费'
  if (a.price_form === 'unknown' || a.price_min == null) return '票价未知'
  const symbol = a.currency === 'CNY' ? '¥' : (a.currency || '') + ' '
  if (a.price_form === 'range' && a.price_max != null) return symbol + money(a.price_min) + '–' + money(a.price_max)
  return symbol + money(a.price_min) + (a.price_form === 'from' ? ' 起' : '')
}
function safeLink(value) {
  try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) ? u.href : null } catch { return null }
}
function clearBudget() { budget.value = ''; nextTick(() => budgetInput.value?.focus()) }
onMounted(() => loadDataset())
</script>

<template>
  <header class="header"><div class="wrap mast">
    <a class="brand" href="#top" aria-label="山河图鉴，回到顶部"><span class="logo" aria-hidden="true"><i></i><b></b></span>山河图鉴</a>
    <nav aria-label="页内导航"><a href="#filters" class="active">偏好推荐</a><a href="#results">推荐结果</a><button type="button" @click="showPanel('dataset')">数据说明</button></nav>
  </div></header>
  <main id="top">
    <section class="hero"><div class="wrap hero-inner">
      <h1>偏好推荐</h1><p>按地区、兴趣和单景点门票预算，找到想去的地方。</p>
    </div></section>
    <div class="wrap">
      <div v-if="datasetError" role="alert" class="state"><h2>数据暂未就绪</h2><p>{{ datasetError }}</p><button class="secondary" @click="loadDataset()">重新连接</button></div>
      <div v-else-if="!info" class="state" role="status">正在读取数据批次…</div>
      <template v-else>
        <div class="data-strip"><span class="status" :class="{test}">{{ test ? '演示样本' : '已接入真实批次' }}</span><span>数据截至 {{ month }}</span><button @click="showPanel('dataset')">查看说明 <span aria-hidden="true">↗</span></button></div>
        <form id="filters" class="filters" @submit.prevent="submit()">
          <label>目的地区<select v-model="region"><option value="">全部地区</option><optgroup v-for="grp in regionGroups" :key="grp.name" :label="grp.name"><option v-for="r in grp.values" :key="r.key" :value="r.key">{{ r.name }}{{ r.level === 'province' ? ' · 全省级地区' : '' }}</option></optgroup></select></label>
          <label>兴趣类型<select v-model="interest"><option value="">不限兴趣</option><option v-for="t in dict.types" :key="t.code" :value="t.code">{{ t.label }}</option></select></label>
          <label>单景点门票预算
            <select v-if="client.amounts" ref="budgetInput" v-model="budget"><option value="">不限预算</option><option v-for="v in client.amounts" :key="v" :value="v">{{ v }} 元</option></select>
            <span v-else class="amount"><input ref="budgetInput" v-model="budget" inputmode="decimal" placeholder="不限预算" :disabled="!policies.length"><span>{{ currentPolicy?.currency === 'CNY' ? '元' : currentPolicy?.currency }}</span></span>
          </label>
          <button class="primary" type="submit" :disabled="busy">{{ busy ? '正在推荐…' : '查看推荐' }} <span aria-hidden="true">→</span></button>
          <label v-if="policies.length > 1 || (policies.length && !policy)" class="policy">票价口径<select v-model="policy"><option value="">请选择</option><option v-for="p in policies" :value="p.id" :key="p.id">{{ p.ticket_basis }} · {{ p.currency }}</option></select></label>
        </form>
        <p v-if="!policies.length" class="notice">价格比较口径暂未确定，仍可按地区或兴趣选择。</p>
        <div class="mode-row"><span class="mode-label">排序偏好</span><div class="modes" role="group" aria-label="排序偏好"><button v-for="(label, key) in modes" :key="key" :aria-pressed="mode === key" @click="mode = key">{{ label }}</button></div></div>
        <section id="results" class="results" aria-live="polite" :aria-busy="busy">
          <div class="result-head"><h2>推荐结果</h2><span v-if="result">{{ result.candidate_count }} 个匹配景点<span v-if="result.candidate_count > result.returned_count"> · 展示前 {{ result.returned_count }} 个</span></span></div>
          <p v-if="note" class="notice">{{ note }}</p>
          <div v-if="searchError" class="state compact" role="alert">{{ searchError }}</div>
          <div v-else-if="busy" class="state compact">正在查找符合条件的景点…</div>
          <div v-else-if="!result" class="state compact">选好偏好后，点击“查看推荐”。</div>
          <div v-else-if="!result.items.length" class="state"><h3>暂无匹配景点</h3><p>{{ result.preferences.budget?.amount === '0.00' ? '当前条件下，暂无已确认免费的景点。' : '当前批次没有符合全部所选条件的景点。' }}</p><p v-if="result.preferences.budget">票价未知的景点不参与预算匹配。</p><button v-if="result.preferences.budget" class="secondary" @click="clearBudget">清除预算</button></div>
          <div v-else class="cards"><article v-for="item in result.items" :key="item.attraction.attraction_id" class="card">
            <div class="location"><span class="marker" aria-hidden="true"></span>{{ [item.attraction.province_name, item.attraction.city_name].filter(Boolean).join(' · ') || '地区未标明' }}</div>
            <h3>{{ item.attraction.name }}</h3>
            <div class="price"><strong>{{ ticket(item.attraction) }}</strong><span>{{ item.attraction.price_basis || '暂无可比票价说明' }}</span></div>
            <ul class="reasons"><li v-for="why in item.reasons" :key="why">{{ why }}</li></ul>
            <button class="text-link" @click="showDetail(item.attraction)">景点详情与来源 <span aria-hidden="true">↗</span></button>
          </article></div>
          <p v-for="w in result?.algorithm_info?.warnings || []" :key="w" class="notice">{{ w }}</p>
        </section>
      </template>
    </div>
  </main>
  <footer class="wrap"><span>山河图鉴</span><span>旅游景点数据分析与智能推荐系统</span></footer>

  <dialog ref="dialog" aria-labelledby="panel-title" @click="e => { if (e.target === dialog) dialog.close() }">
    <div class="dialog-inner"><button class="close" aria-label="关闭" @click="dialog.close()">×</button>
      <template v-if="panel === 'dataset'"><h2 id="panel-title">数据说明</h2>
        <p v-if="!info">尚未读取可用批次。</p>
        <template v-else><p><b>{{ test ? '演示样本' : '真实批次' }}</b> · {{ info.standard_count.toLocaleString() }} 条候选记录 · {{ month }}</p>
          <p v-if="test">此页面使用构造样本验证筛选和推荐交互，名称与票价示例参考项目交接记录。</p>
          <p>预算仅指单个景点的基础门票。价格未知的记录可以参与地区或兴趣推荐，设置预算后仅匹配符合所选票价口径的记录。</p>
          <p v-if="client.amounts">离线预览提供预设预算；各选项的结果已由项目推荐函数生成。</p>
          <p v-if="info.quality?.notes">{{ Array.isArray(info.quality.notes) ? info.quality.notes.join('；') : info.quality.notes }}</p>
          <h3 v-if="info.sources?.length">数据来源</h3><ul><li v-for="s in info.sources" :key="s.source_id"><a v-if="safeLink(s.base_url)" :href="s.base_url" target="_blank" rel="noopener noreferrer">{{ s.name }}</a><span v-else>{{ s.name }}</span></li></ul>
          <small>批次 {{ meta.batch_id }}</small>
        </template>
      </template>
      <template v-else><h2 id="panel-title">{{ detailRecord?.attraction.name || '景点详情' }}</h2>
        <p v-if="detailBusy">正在读取详情…</p><p v-else-if="detailError" role="alert">{{ detailError }}</p>
        <template v-else-if="detailRecord"><p>{{ detailRecord.attraction.province_name }} · {{ detailRecord.attraction.city_name }}</p>
          <h3>票价依据</h3><p>{{ ticket(detailRecord.attraction) }} · {{ detailRecord.attraction.price_raw || detailRecord.attraction.price_basis || '暂无票价资料' }}</p>
          <h3>来源记录</h3><p v-if="!detailRecord.evidence.length">这条记录暂无可展示的来源。</p>
          <ul><li v-for="e in detailRecord.evidence" :key="e.source_ref"><a v-if="safeLink(e.source_url)" :href="e.source_url" target="_blank" rel="noopener noreferrer">{{ info.sources?.find(s => s.source_id === e.source_id)?.name || e.source_id }} ↗</a><span v-else>{{ e.source_id }}</span> <small>{{ e.source_date }}</small></li></ul>
          <small v-if="test">演示样本 · {{ month }}</small>
        </template>
      </template>
    </div>
  </dialog>
</template>
