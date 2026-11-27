import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

async function start() {
  const encoded = document.querySelector('#recordings').textContent.trim()
  const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0))
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))
  const book = await new Response(stream).json()
  function pageOf(items, p) {
    const page=Number(p.page || 1), size=Number(p.page_size || 20)
    return {meta:book.dataset.meta,error:null,data:{total:items.length,page,page_size:size,total_pages:Math.ceil(items.length/size),items:items.slice((page-1)*size,page*size)}}
  }
  const client = {
    list: async p => {
      if(p.max_price!==undefined && !/^(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?$/.test(p.max_price))
        throw Object.assign(new Error('请输入非负金额，最多两位小数。'),{code:'INVALID_PARAMETER'})
      const rows=book.lists[p.sort || 'name_asc'].filter(r=>
        (!p.q || r.name.includes(p.q)) && (!p.type_code || r.type_codes.includes(p.type_code)) &&
        ['city_key','province_key','grade_status','grade_system','grade_level'].every(k=>!p[k] || r[k]===p[k]) &&
        (p.max_price===undefined || (r.price_policy_id===p.price_policy_id && r.currency===p.currency && r.price_min!==null && Number(r.price_min)<=Number(p.max_price))))
      return pageOf(rows,p)
    },
    statistics: async p => {
      const rows=book.stats[p.metric+'|'+p.scope]
      if(!rows)throw Object.assign(new Error('此演示样本未提供该统计。'),{code:'STATISTIC_NOT_AVAILABLE'})
      return pageOf(rows,p)
    },
    amounts: book.amounts,
    dataset: async () => book.dataset,
    detail: async (id) => book.details[id],
    recommend: async p => {
      const key = [p.province_key || p.city_key || '', p.type_codes[0] || '', p.mode, p.budget?.amount || ''].join('|')
      const reply = book.results[key]
      if (!reply) throw Object.assign(new Error('请重新选择演示条件。'), { code: 'INVALID_FILTER' })
      return reply
    },
  }
  createApp(App, { client }).mount('#app')
}
start().catch(() => {
  document.getElementById('app').textContent = '当前浏览器暂不支持此离线版，请使用新版 Edge、Chrome、Firefox 或 Safari 打开。'
})
