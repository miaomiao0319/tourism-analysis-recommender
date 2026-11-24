import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

async function start() {
  const encoded = document.querySelector('#recordings').textContent.trim()
  const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0))
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))
  const book = await new Response(stream).json()
  const client = {
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
