import { createApp } from 'vue'
import App from './App.vue'
import { client } from './transport.js'
import './style.css'

createApp(App, { client }).mount('#app')
