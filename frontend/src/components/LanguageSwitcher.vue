<template>
  <label class="language-switcher">
    <span class="sr-only">Language</span>
    <select :value="locale" aria-label="Language" :disabled="switching" @change="changeLocale">
      <option v-for="item in supportedLocales" :key="item.code" :value="item.code">{{ item.label }}</option>
    </select>
  </label>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from '../core/i18n.js'
import { authedFetch, getToken } from '../core/authStore.js'

const { locale, setLocale, supportedLocales } = useI18n()
const switching = ref(false)
const API_BASE = import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL || 'http://localhost:8001'

async function changeLocale(event) {
  const next = event.target.value
  if (next === locale.value) return
  switching.value = true
  try {
    // Save the display preference without interrupting the active evaluation.
    // Agent prompts adopt the new language when the next run starts.
    if (getToken()) {
      const response = await authedFetch(`${API_BASE}/control/locale`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ locale: next }),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
    }
    setLocale(next)
    if (getToken()) window.location.reload()
  } catch (error) {
    console.error('[i18n] locale switch failed', error)
    event.target.value = locale.value
  } finally {
    switching.value = false
  }
}
</script>

<style scoped>
.language-switcher select {
  border: 1px solid rgba(105, 220, 255, .25);
  border-radius: 8px;
  background: rgba(7, 18, 32, .8);
  color: #d8f4ff;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  padding: 5px 8px;
}
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
</style>
