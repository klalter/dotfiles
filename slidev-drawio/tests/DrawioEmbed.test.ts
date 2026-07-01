import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import DrawioEmbed from '../components/DrawioEmbed.vue'

const SAMPLE_XML = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>'

function mockFetch(xml: string) {
  ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true,
    text: () => Promise.resolve(xml),
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('DrawioEmbed', () => {
  it('renders with default props', async () => {
    mockFetch(SAMPLE_XML)
    const wrapper = mount(DrawioEmbed, { props: { src: '/test.drawio' } })
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('[data-testid="drawio-embed"]').exists()).toBe(true)
  })

  it('shows loading state initially', () => {
    ;(global.fetch as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    const wrapper = mount(DrawioEmbed, { props: { src: '/test.drawio' } })
    expect(wrapper.find('.drawio-loading').exists()).toBe(true)
  })

  it('renders iframe after successful load', async () => {
    mockFetch(SAMPLE_XML)
    const wrapper = mount(DrawioEmbed, { props: { src: '/test.drawio' } })
    await flushPromises()
    expect(wrapper.find('iframe').exists()).toBe(true)
    expect(wrapper.find('.drawio-loading').exists()).toBe(false)
  })

  it('shows error state on fetch failure', async () => {
    ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 404,
    })
    const wrapper = mount(DrawioEmbed, { props: { src: '/missing.drawio' } })
    await flushPromises()
    expect(wrapper.find('.drawio-error').exists()).toBe(true)
    expect(wrapper.find('iframe').exists()).toBe(false)
  })

  it('hides edit button when editable=false', async () => {
    mockFetch(SAMPLE_XML)
    const wrapper = mount(DrawioEmbed, { props: { src: '/test.drawio', editable: false } })
    await flushPromises()
    expect(wrapper.find('[data-testid="drawio-edit-btn"]').exists()).toBe(false)
  })

  it('shows edit button when editable=true', async () => {
    mockFetch(SAMPLE_XML)
    const wrapper = mount(DrawioEmbed, { props: { src: '/test.drawio', editable: true } })
    await flushPromises()
    expect(wrapper.find('[data-testid="drawio-edit-btn"]').exists()).toBe(true)
  })

  it('opens editor on edit button click', async () => {
    mockFetch(SAMPLE_XML)
    const wrapper = mount(DrawioEmbed, { props: { src: '/test.drawio', editable: true } })
    await flushPromises()
    await wrapper.find('[data-testid="drawio-edit-btn"]').trigger('click')
    expect(wrapper.findComponent({ name: 'DrawioEditor' }).exists()).toBe(true)
  })

  it('applies theme class', async () => {
    mockFetch(SAMPLE_XML)
    const wrapper = mount(DrawioEmbed, { props: { src: '/test.drawio', theme: 'dark' } })
    expect(wrapper.find('[data-testid="drawio-embed"]').classes()).toContain('drawio-theme-dark')
  })

  it('applies border class when border=true', () => {
    ;(global.fetch as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    const wrapper = mount(DrawioEmbed, { props: { src: '/test.drawio', border: true } })
    expect(wrapper.find('[data-testid="drawio-embed"]').classes()).toContain('with-border')
  })

  it('applies shadow class when shadow=true', () => {
    ;(global.fetch as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    const wrapper = mount(DrawioEmbed, { props: { src: '/test.drawio', shadow: true } })
    expect(wrapper.find('[data-testid="drawio-embed"]').classes()).toContain('with-shadow')
  })

  it('sets custom dimensions', () => {
    ;(global.fetch as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    const wrapper = mount(DrawioEmbed, {
      props: { src: '/test.drawio', width: '600px', height: '300px' },
    })
    const el = wrapper.find('[data-testid="drawio-embed"]').element as HTMLElement
    expect(el.style.width).toBe('600px')
    expect(el.style.height).toBe('300px')
  })

  it('emits save event when editor saves', async () => {
    mockFetch(SAMPLE_XML)
    const wrapper = mount(DrawioEmbed, { props: { src: '/test.drawio', editable: true } })
    await flushPromises()
    await wrapper.find('[data-testid="drawio-edit-btn"]').trigger('click')

    const newXml = '<mxGraphModel><root><mxCell id="0"/></root></mxGraphModel>'
    wrapper.findComponent({ name: 'DrawioEditor' }).vm.$emit('save', newXml)
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('save')).toBeTruthy()
    expect(wrapper.emitted('save')![0]).toEqual([newXml])
  })
})
