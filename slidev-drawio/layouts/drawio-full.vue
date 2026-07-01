<template>
  <div class="slidev-layout drawio-layout">
    <DrawioFull
      :src="src"
      :editable="editable"
      :theme="theme"
      :title="title"
    >
      <!-- Pass through any slot content as overlay -->
      <slot />
    </DrawioFull>
  </div>
</template>

<script setup>
import DrawioFull from '../components/DrawioFull.vue'

/**
 * Slidev layout for full-page draw.io diagrams.
 *
 * Usage in slides.md frontmatter:
 *   ---
 *   layout: drawio-full
 *   src: /diagrams/architecture.drawio
 *   editable: true
 *   theme: dark
 *   title: System Architecture
 *   ---
 */
defineProps({
  /** Path to the .drawio file (relative to Slidev public dir) */
  src: {
    type: String,
    required: true
  },
  /** Allow live editing via the draw.io editor */
  editable: {
    type: Boolean,
    default: false
  },
  /** Visual theme: 'modern' | 'dark' | 'neon' | 'minimal' */
  theme: {
    type: String,
    default: 'modern'
  },
  /** Optional title displayed as an overlay at the top */
  title: {
    type: String,
    default: ''
  }
})
</script>

<style>
.drawio-layout {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 0 !important;
  margin: 0;
  overflow: hidden;
  position: relative;
}
</style>
