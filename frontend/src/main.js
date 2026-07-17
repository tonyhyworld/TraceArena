import { createApp } from 'vue'
import App from './App.vue'
import { locale } from './core/i18n.js'

document.documentElement.lang = locale.value
createApp(App).mount('#app')
