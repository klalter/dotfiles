<template>
  <div
    class="drawio-container drawio-full-container"
    :class="[`drawio-theme-${theme}`]"
    data-testid="drawio-full"
  >
    <!-- Optional title overlay -->
    <div v-if="title" class="drawio-full-title-overlay">
      <h1 class="drawio-full-title-text">{{ title }}</h1>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="drawio-loading" aria-live="polite">
      <div class="drawio-loading-spinner" role="status" aria-label="Loading diagram"></div>
      <span class="drawio-loading-text">Loading diagram&hellip;</span>
    </div>

    <!-- Error state -->
    <div v-else-if="errorMsg" class="drawio-error" role="alert">
      <div class="drawio-error-icon" aria-hidden="true">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      </div>
      <div class="drawio-error-title">Failed to load diagram</div>
      <div class="drawio-error-message">{{ errorMsg }}</div>
    </div>

    <!-- Diagram viewer — full coverage -->
    <template v-else>
      <iframe
        class="drawio-iframe drawio-full-iframe"
        :src="viewerUrl"
        :title="iframeTitle"
        frameborder="0"
        scrolling="no"
        sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
      />

      <!-- Edit button -->
      <button
        v-if="editable"
        class="drawio-edit-btn drawio-full-edit-btn"
        @click="openEditor"
        aria-label="Edit diagram in draw.io"
        data-testid="drawio-full-edit-btn"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
        Edit
      </button>
    </template>

    <!-- Slot for additional overlay content -->
    <slot />

    <!-- Editor modal -->
    <DrawioEditor
      v-if="editing"
      :xml="xml"
      @save="handleSave"
      @close="editing = false"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import DrawioEditor from './DrawioEditor.vue'

const props = defineProps({
  /** Path to the .drawio file, relative to Slidev public dir */
  src: {
    type: String,
    required: true
  },
  /** Show an Edit button that opens the live draw.io editor */
  editable: {
    type: Boolean,
    default: false
  },
  /** Visual theme: 'modern' | 'dark' | 'neon' | 'minimal' */
  theme: {
    type: String,
    default: 'modern',
    validator: (v) => ['modern', 'dark', 'neon', 'minimal'].includes(v)
  },
  /** Optional title displayed as an overlay at the top of the diagram */
  title: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['save'])

const xml = ref('')
const loading = ref(true)
const errorMsg = ref('')
const editing = ref(false)

const iframeTitle = computed(() => {
  const filename = props.src.split('/').pop() || 'diagram'
  return `draw.io diagram: ${filename}`
})

const viewerUrl = computed(() => {
  if (!xml.value) return ''
  const encoded = encodeURIComponent(xml.value)
  return `https://viewer.diagrams.net/?lightbox=0&highlight=0000ff&nav=1&toolbar=0&fit=1&xml=${encoded}`
})

async function loadDiagram() {
  loading.value = true
  errorMsg.value = ''

  try {
    const base = (typeof import.meta !== 'undefined' && import.meta.env?.BASE_URL) ?? '/'
    const url = props.src.startsWith('http')
      ? props.src
      : props.src.startsWith('/')
        ? props.src
        : `${base.replace(/\/$/, '')}/${props.src}`

    const res = await fetch(url)
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} — could not fetch "${url}"`)
    }
    const text = await res.text()
    if (!text.trim()) {
      throw new Error('The diagram file is empty')
    }
    xml.value = text
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

function openEditor() {
  editing.value = true
}

function handleSave(newXml) {
  xml.value = newXml
  editing.value = false
  emit('save', newXml)
}

onMounted(() => {
  if (typeof window !== 'undefined') {
    loadDiagram()
  } else {
    loading.value = false
    errorMsg.value = 'Diagrams cannot be rendered server-side'
  }
})
</script>

<style>
@import '../styles/base.css';
@import '../styles/theme-modern.css';
@import '../styles/theme-dark.css';
@import '../styles/theme-neon.css';
@import '../styles/theme-minimal.css';

.drawio-full-container {
  width: 100%;
  height: 100%;
  border-radius: 0;
  border: none;
  box-shadow: none;
}

.drawio-full-iframe {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.drawio-full-title-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 10;
  padding: 20px 32px 12px;
  background: linear-gradient(to bottom, rgba(0, 0, 0, 0.55) 0%, transparent 100%);
  pointer-events: none;
}

.drawio-full-title-text {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
  color: #ffffff;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.45);
  font-family: system-ui, -apple-system, sans-serif;
  letter-spacing: -0.01em;
}

.drawio-full-edit-btn {
  top: 16px;
  right: 16px;
}
</style>
