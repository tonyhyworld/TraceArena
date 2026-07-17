<template>
  <div class="uam" :class="[`uam-${variant}`, { open }]">
    <button class="uam-trigger" @click="open = !open" :title="user?.display_name || user?.username">
      <span class="uam-avatar">{{ avatarLetter }}</span>
      <span v-if="variant === 'sidebar'" class="uam-info">
        <span class="uam-name">{{ user?.display_name || user?.username || t('account.user') }}</span>
        <span class="uam-role">{{ user?.is_admin ? t('account.admin') : t('account.signed_in') }}</span>
      </span>
      <span v-else-if="variant === 'hud'" class="uam-hud-label">{{ t('account.label') }}</span>
      <svg class="uam-chevron" viewBox="0 0 20 20" width="14" height="14" aria-hidden="true">
        <path d="M5 8l5 5 5-5" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      </svg>
    </button>

    <div v-if="open" class="uam-menu">
      <div class="uam-menu-head">
        <strong>{{ user?.display_name || user?.username }}</strong>
        <span>@{{ user?.username }}</span>
      </div>
      <button class="uam-item" @click="openProfile">{{ t('account.profile') }}</button>
      <button v-if="showViewerLink" class="uam-item" @click="goViewer">{{ t('account.viewer') }}</button>
      <button v-if="showOperatorLink" class="uam-item" @click="goOperator">{{ t('account.operator') }}</button>
      <LanguageSwitcher class="uam-locale" />
      <div class="uam-divider"></div>
      <button class="uam-item danger" @click="doLogout">{{ t('account.logout') }}</button>
    </div>

    <ProfileCenter v-if="showProfile" @close="showProfile = false" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getCurrentUser, logout, hasPermission } from '../core/authStore.js'
import { navigateView } from '../core/viewNav.js'
import ProfileCenter from '../auth/ProfileCenter.vue'
import LanguageSwitcher from './LanguageSwitcher.vue'
import { t } from '../core/i18n.js'

const props = defineProps({
  variant: { type: String, default: 'sidebar' },
})

const user = ref(getCurrentUser())
const open = ref(false)
const showProfile = ref(false)

const avatarLetter = computed(() => {
  const name = user.value?.display_name || user.value?.username || '?'
  return name.charAt(0).toUpperCase()
})

const showViewerLink = computed(() => props.variant === 'sidebar' && hasPermission('access_viewer'))
const showOperatorLink = computed(() => props.variant === 'hud' && hasPermission('access_operator'))

function onDocClick(e) {
  if (!e.target.closest?.('.uam')) open.value = false
}

function openProfile() {
  open.value = false
  showProfile.value = true
}

function doLogout() {
  open.value = false
  logout()
}

function goViewer() {
  open.value = false
  navigateView('viewer')
}

function goOperator() {
  open.value = false
  navigateView('operator')
}

onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

<style scoped>
.uam { position: relative; }

.uam-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.2);
  color: #d8d2ef;
  cursor: pointer;
  text-align: left;
}

.uam-hud .uam-trigger {
  width: auto;
  padding: 6px 10px 6px 6px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.35);
  border-color: rgba(105, 220, 255, 0.2);
}

.uam-trigger:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(105, 220, 255, 0.25);
}

.uam-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  flex-shrink: 0;
  background: linear-gradient(135deg, #69dcff, #8b5bff);
  color: #06121f;
  font-size: 14px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
}

.uam-hud .uam-avatar {
  width: 28px;
  height: 28px;
  font-size: 12px;
}

.uam-hud-label {
  font-size: 12px;
  font-weight: 600;
  color: rgba(200, 230, 255, 0.9);
  padding-right: 2px;
}

.uam-hud .uam-menu {
  z-index: 10030;
}

.uam-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.uam-name {
  font-size: 13px;
  font-weight: 600;
  color: #f0ecff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.uam-role {
  font-size: 11px;
  color: #8a82a6;
}

.uam-chevron {
  flex-shrink: 0;
  color: #8a82a6;
  transition: transform 0.15s;
}

.uam.open .uam-chevron {
  transform: rotate(180deg);
}

.uam-menu {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + 8px);
  z-index: 100;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  background: #1a1234;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
  padding: 6px;
  min-width: 180px;
}

.uam-hud .uam-menu {
  left: auto;
  right: 0;
  bottom: auto;
  top: calc(100% + 8px);
  width: 200px;
}

.uam-menu-head {
  padding: 8px 10px 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 4px;
}

.uam-locale {
  display: block;
  padding: 6px 8px;
}

.uam-menu-head strong {
  display: block;
  font-size: 13px;
  color: #f0ecff;
}

.uam-menu-head span {
  font-size: 11px;
  color: #8a82a6;
}

.uam-item {
  width: 100%;
  text-align: left;
  border: none;
  background: none;
  color: #d8d2ef;
  font-size: 13px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
}

.uam-item:hover {
  background: rgba(105, 220, 255, 0.1);
  color: #eafaff;
}

.uam-item.danger { color: #ff8a80; }
.uam-item.danger:hover { background: rgba(255, 95, 82, 0.12); }

.uam-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.06);
  margin: 4px 0;
}
</style>
