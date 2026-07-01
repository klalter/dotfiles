import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import DrawioFull from '../components/DrawioFull.vue'

const SAMPLE_XML = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>'

beforeEach(() => {
  vi.clearAllMocks()
  ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true,
    text: () => Promise.resolve(SAMPLE_XML),
  })
})

describe('DrawioFull', () => {
  it('renders full-page container', () => {
    const wrapper = mount(DrawioFull, { props: { src: '/test.drawio' } })
    expect(wrapper.find('[data-testid="drawio-full"]').exists()).toBe(true)
  })

  it('renders iframe after load', async () => {
    const wrapper = mount(DrawioFull, { props: { src: '/test.drawio' } })
    await flushPromises()
    expect(wrapper.find('iframe').exists()).toBe(true)
  })

  it('shows title overlay when title prop is set', async () => {
    const wrapper = mount(DrawioFull, {
      props: { src: '/test.drawio', title: 'My Architecture' },
    })
    await flushPromises()
    expect(wrapper.find('.drawio-full-title-overlay').exists()).toBe(true)
    expect(wrapper.find('.drawio-full-title-text').text()).toBe('My Architecture')
  })

  it('hides title overlay when title is empty', async () => {
    const wrapper = mount(DrawioFull, { props: { src: '/test.drawio' } })
    await flushPromises()
    expect(wrapper.find('.drawio-full-title-overlay').exists()).toBe(false)
  })

  it('applies theme class', () => {
    const wrapper = mount(DrawioFull, { props: { src: '/test.drawio', theme: 'neon' } })
    expect(wrapper.find('[data-testid="drawio-full"]').classes()).toContain('drawio-theme-neon')
  })

  it('shows edit button when editable=true', async () => {
    const wrapper = mount(DrawioFull, { props: { src: '/test.drawio', editable: true } })
    await flushPromises()
    expect(wrapper.find('[data-testid="drawio-full-edit-btn"]').exists()).toBe(true)
  })
})
