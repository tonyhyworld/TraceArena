<template>
  <label class="language-switcher">
    <span class="sr-only">Language</span>
    <select :value="locale" aria-label="Language" @change="setLocale($event.target.value)">
      <option v-for="item in supportedLocales" :key="item.code" :value="item.code">{{ item.label }}</option>
    </select>
  </label>
</template>

<script setup>
import { useI18n } from '../core/i18n.js'

const { locale, setLocale, supportedLocales } = useI18n()
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
