import { readonly, ref } from 'vue'

export const SUPPORTED_LOCALES = [
  { code: 'zh-CN', label: '简体中文' },
  { code: 'en-US', label: 'English' },
]

const STORAGE_KEY = 'tracearena.locale'
const fallbackLocale = 'zh-CN'
const saved = typeof window === 'undefined' ? null : window.localStorage.getItem(STORAGE_KEY)
export const locale = ref(SUPPORTED_LOCALES.some(item => item.code === saved) ? saved : fallbackLocale)

const messages = {
  'zh-CN': {
    'app.no_access': '当前账号没有使用此功能的权限，请联系管理员开通。',
    'account.user': '用户', 'account.admin': '超级管理员', 'account.signed_in': '已登录',
    'account.label': '账户', 'account.profile': '个人中心', 'account.viewer': '观众端',
    'account.operator': '运营后台', 'account.logout': '退出登录',
    'login.title': '登录 AI World', 'login.tagline': '定义专业世界，让多个 Agent 竞争并寻找更优路径',
    'login.value_label': 'AI World 核心能力', 'login.value_define': '世界可定义',
    'login.value_compete': '多路径竞争', 'login.value_visible': '全过程可见',
    'login.username': '用户名', 'login.password': '密码', 'login.username_placeholder': '输入你的账号',
    'login.submit': '登录并进入世界', 'login.loading': '正在进入世界…',
    'login.ready': 'AI World OS 已就绪 · 场景包可加载', 'login.required': '请输入用户名和密码',
    'login.failed': '登录失败',
  },
  'en-US': {
    'app.no_access': 'This account does not have access to this feature. Contact an administrator to request access.',
    'account.user': 'User', 'account.admin': 'Administrator', 'account.signed_in': 'Signed in',
    'account.label': 'Account', 'account.profile': 'Profile', 'account.viewer': 'Viewer',
    'account.operator': 'Operations console', 'account.logout': 'Sign out',
    'login.title': 'Sign in to AI World', 'login.tagline': 'Define a domain world and let agents compete for better paths',
    'login.value_label': 'AI World capabilities', 'login.value_define': 'Define the world',
    'login.value_compete': 'Compare paths', 'login.value_visible': 'Watch the process',
    'login.username': 'Username', 'login.password': 'Password', 'login.username_placeholder': 'Enter your account name',
    'login.submit': 'Sign in and enter', 'login.loading': 'Entering the world…',
    'login.ready': 'AI World OS ready · Scenario packs loadable', 'login.required': 'Enter a username and password',
    'login.failed': 'Sign-in failed',
  },
}

export function setLocale(next) {
  if (!SUPPORTED_LOCALES.some(item => item.code === next)) return
  locale.value = next
  if (typeof window !== 'undefined') window.localStorage.setItem(STORAGE_KEY, next)
  document.documentElement.lang = next
}

export function t(key, fallback = key) {
  return messages[locale.value]?.[key] || messages[fallbackLocale]?.[key] || fallback
}

export function useI18n() {
  return { locale: readonly(locale), setLocale, t, supportedLocales: SUPPORTED_LOCALES }
}
