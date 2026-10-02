import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'

import { createVuetify } from 'vuetify'
import { aliases, mdi } from 'vuetify/iconsets/mdi'

/** Vuetify 实例：亮/暗两套主题，图标使用 Material Design Icons。 */
export const vuetify = createVuetify({
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: { mdi },
  },
  theme: {
    defaultTheme: 'jmbotLight',
    themes: {
      jmbotLight: {
        dark: false,
        colors: {
          primary: '#1976d2',
          secondary: '#455a64',
          success: '#2e7d32',
          warning: '#ed6c02',
          error: '#c62828',
          background: '#f4f6f8',
          surface: '#ffffff',
        },
      },
      jmbotDark: {
        dark: true,
        colors: {
          primary: '#64b5f6',
          secondary: '#90a4ae',
          success: '#81c784',
          warning: '#ffb74d',
          error: '#e57373',
          background: '#121212',
          surface: '#1e1e1e',
        },
      },
    },
  },
  defaults: {
    VBtn: {
      // 触控区域不小于 44px，满足移动端要求
      minHeight: 44,
    },
    VTextField: {
      variant: 'outlined',
      density: 'comfortable',
    },
  },
})
