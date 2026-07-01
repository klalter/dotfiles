<template>
  <div
    class="drawio-container"
    :class="[
      `drawio-theme-${theme}`,
      { 'with-border': border, 'with-shadow': shadow }
    ]"
    :style="{ width, height }"
    data-testid="drawio-embed"
  >
    <!-- Loading state -->
    <div v-if="loading" class="drawio-loading" aria-live="polite">
      <div class="drawio-loading-spinner" role="status" aria-label="Loading diagram"></div>
      <span class="drawio-loading-text">Loading diagram&hellip;</span>
    </div>

    <!-- Error state -->
    <div v-else-if="errorMsg" class="drawio-error" role="alert">
      <div class="drawio-error-icon" aria-hidden="true">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      </div>
      <div class="drawio-error-title">Failed to load diagram</div>
      <div class="drawio-error-message">{{ errorMsg }}</div>
    </div>

    <!-- Diagram viewer -->
    <template v-else>
      <iframe
        class="drawio-iframe"
        :src="viewerUrl"
        :title="iframeTitle"
        frameborder="0"
        scrolling="no"
        sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
      />

      <!-- Edit button -->
      <button
        v-if="editable"
        class="drawio-edit-btn"
        @click="openEditor"
        aria-label="Edit diagram in draw.io"
        data-testid="drawio-edit-btn"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
        Edit
      </button>
    </template>

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
  /** Container width */
  width: {
    type: String,
    default: '100%'
  },
  /** Container height */
  height: {
    type: String,
    default: '400px'
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
  /** Show border around the container */
  border: {
    type: Boolean,
    default: true
  },
  /** Show drop shadow */
  shadow: {
    type: Boolean,
    default: true
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

/**
 * Build the viewer URL from the fetched XML.
 * Uses the viewer.diagrams.net embed endpoint.
 */
const viewerUrl = computed(() => {
  if (!xml.value) return ''
  // Encode the XML for the URL parameter
  const encoded = encodeURIComponent(xml.value)
  return `https://viewer.diagrams.net/?lightbox=0&highlight=0000ff&nav=1&toolbar=0&xml=${encoded}`
})

async function loadDiagram() {
  loading.value = true
  errorMsg.value = ''

  try {
    // Build the fetch URL — respect BASE_URL for Slidev projects
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
  // Guard against SSR
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
</style>
