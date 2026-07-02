<template>
  <Teleport to="body">
    <div
      class="drawio-editor-overlay"
      @click.self="handleClose"
      role="dialog"
      aria-modal="true"
      aria-label="draw.io diagram editor"
    >
      <div class="drawio-editor-modal">
        <div class="drawio-editor-header">
          <div class="drawio-editor-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
            Edit Diagram
          </div>
          <button
            class="drawio-editor-close"
            @click="handleClose"
            aria-label="Close editor"
            title="Close editor (Esc)"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div v-if="editorLoading" class="drawio-editor-loading">
          <div class="drawio-editor-loading-inner">
            <div class="drawio-editor-spinner"></div>
            <span>Loading editor&hellip;</span>
          </div>
        </div>

        <iframe
          ref="editorIframe"
          class="drawio-editor-iframe"
          :src="editorUrl"
          title="draw.io diagram editor"
          allow="clipboard-read; clipboard-write"
          frameborder="0"
          allowfullscreen
        />
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  xml: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['save', 'close', 'export'])

const editorIframe = ref(null)
const editorLoading = ref(true)

// The embed.diagrams.net editor URL with json protocol
const editorUrl =
  'https://embed.diagrams.net/?embed=1&proto=json&spin=1&libraries=1&saveAndExit=1&noSaveBtn=0&noExitBtn=0'

function sendToEditor(message) {
  if (!editorIframe.value?.contentWindow) return
  editorIframe.value.contentWindow.postMessage(JSON.stringify(message), '*')
}

function handleMessage(event) {
  // Accept messages from diagrams.net or drawio.com domains
  if (
    !event.origin.includes('diagrams.net') &&
    !event.origin.includes('drawio.com') &&
    event.origin !== window.location.origin
  ) {
    return
  }

  let msg
  try {
    msg = typeof event.data === 'string' ? JSON.parse(event.data) : event.data
  } catch {
    return
  }

  if (!msg || !msg.event) return

  switch (msg.event) {
    case 'init':
      // Editor is ready — send the XML to load
      editorLoading.value = false
      sendToEditor({ action: 'load', xml: props.xml })
      break

    case 'load':
      // XML has been loaded into the editor
      editorLoading.value = false
      break

    case 'save':
      if (msg.xml) {
        emit('save', msg.xml)
      }
      break

    case 'exit':
    case 'close':
      emit('close')
      break

    case 'export':
      // SVG export data returned
      if (msg.data) {
        emit('export', msg.data)
      }
      break

    default:
      break
  }
}

function handleClose() {
  emit('close')
}

function handleKeydown(event) {
  if (event.key === 'Escape') {
    handleClose()
  }
}

onMounted(() => {
  if (typeof window !== 'undefined') {
    window.addEventListener('message', handleMessage)
    window.addEventListener('keydown', handleKeydown)
  }
})

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('message', handleMessage)
    window.removeEventListener('keydown', handleKeydown)
  }
})
</script>

<style>
@import '../styles/base.css';
</style>
