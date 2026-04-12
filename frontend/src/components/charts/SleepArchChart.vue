<template>
  <div class="chart-wrap">
    <div ref="containerRef" class="chart-container"></div>
    <div class="d3-tooltip" ref="tooltipEl"></div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import * as d3 from 'd3'
import { STAGE_COLORS } from '../../utils/stageColors'

const props = defineProps({ items: { type: Array, default: () => [] } })

const containerRef = ref(null)
const tooltipEl = ref(null)

const stageOrder = ['Awake', 'REM', 'Light', 'Deep']
const stageMap = { awake: 'Awake', rem: 'REM', light: 'Light', deep: 'Deep' }
const stageColors = {
  Awake: STAGE_COLORS.awake,
  REM:   STAGE_COLORS.rem,
  Light: STAGE_COLORS.light,
  Deep:  STAGE_COLORS.deep,
}

const M = { top: 8, right: 16, bottom: 28, left: 52 }
let svg, g, xScale, yScale, gX, gY, resizeObs, W = 600, H = 160

function mergeSegments(stages) {
  if (!stages.length) return []
  const sorted = [...stages].sort((a, b) => a.t - b.t)
  const merged = []
  let cur = { stage: stageMap[sorted[0].stage] || 'Light', startT: sorted[0].t, endT: sorted[0].t }
  for (let i = 1; i < sorted.length; i++) {
    const label = stageMap[sorted[i].stage] || 'Light'
    if (label === cur.stage) {
      cur.endT = sorted[i].t
    } else {
      cur.endT = sorted[i].t
      merged.push(cur)
      cur = { stage: label, startT: sorted[i].t, endT: sorted[i].t }
    }
  }
  const epochMs = sorted.length > 1 ? sorted[1].t - sorted[0].t : 30000
  cur.endT = cur.endT + epochMs
  merged.push(cur)
  return merged
}

function styleAxis(sel) {
  sel.selectAll('text').attr('fill', '#8b8fa3').attr('font-size', '11px')
  sel.selectAll('line,path').attr('stroke', 'none')
}

function init() {
  if (!containerRef.value) return
  d3.select(containerRef.value).selectAll('svg').remove()
  const rect = containerRef.value.getBoundingClientRect()
  W = Math.max(rect.width || 600, 300)
  H = 160
  const iw = W - M.left - M.right
  const ih = H - M.top - M.bottom

  svg = d3.select(containerRef.value).append('svg').attr('width', W).attr('height', H)
  g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`)

  xScale = d3.scaleTime().range([0, iw])
  yScale = d3.scaleBand().domain(stageOrder).range([0, ih]).padding(0.12)

  // Background band tint for the whole sleep area
  g.append('rect')
    .attr('x', 0).attr('y', 0)
    .attr('width', iw).attr('height', ih)
    .attr('fill', 'rgba(56,189,248,0.04)')
    .attr('rx', 4)

  // Horizontal gridlines per band
  stageOrder.forEach(s => {
    const y = yScale(s)
    g.append('line')
      .attr('x1', 0).attr('x2', iw)
      .attr('y1', y + yScale.bandwidth()).attr('y2', y + yScale.bandwidth())
      .attr('stroke', '#2a2e3d').attr('stroke-width', 1)
      .attr('stroke-dasharray', '2,3')
  })

  g.append('g').attr('class', 'block-layer')

  gX = g.append('g').attr('transform', `translate(0,${ih})`)
  gY = g.append('g')

  // Crosshair
  const ch = g.append('g').attr('class', 'crosshair').style('display', 'none')
  ch.append('line').attr('y1', 0).attr('y2', ih)
    .attr('stroke', '#7c6ef0').attr('stroke-dasharray', '3,3').attr('stroke-width', 1)

  svg.on('mousemove', function(ev) {
    const [mx] = d3.pointer(ev, g.node())
    if (mx >= 0 && mx <= iw) {
      ch.style('display', null).attr('transform', `translate(${mx},0)`)
      const tip = tooltipEl.value
      if (tip) {
        tip.style.display = 'block'
        tip.style.left = (ev.offsetX + 12) + 'px'
        tip.style.top = (ev.offsetY - 10) + 'px'
        const t = xScale.invert(mx)
        const tMs = t.getTime()
        const allSegs = props.items.flatMap(it => mergeSegments(it.analysis.sleep_stage_series || []))
        const seg = allSegs.find(s => tMs >= s.startT && tMs < s.endT)
        tip.textContent = d3.timeFormat('%H:%M')(t) + (seg ? ` — ${seg.stage}` : '')
      }
    }
  })
  svg.on('mouseleave', () => {
    ch.style('display', 'none')
    if (tooltipEl.value) tooltipEl.value.style.display = 'none'
  })

  // Zoom
  const zoom = d3.zoom().scaleExtent([1, 20])
    .extent([[M.left, M.top], [M.left + iw, M.top + ih]])
    .translateExtent([[M.left, M.top], [M.left + iw, M.top + ih]])
    .on('zoom', ev => {
      const nx = ev.transform.rescaleX(xScale)
      gX.call(d3.axisBottom(nx).ticks(6).tickFormat(d3.timeFormat('%H:%M'))).call(styleAxis)
      renderData(nx)
    })
  svg.call(zoom)
  svg.on('dblclick.zoom', () => svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity))
}

function renderData(xS) {
  if (!g) return
  xS = xS || xScale
  const iw = W - M.left - M.right

  const allStages = props.items.flatMap(it => it.analysis.sleep_stage_series || [])
  if (!allStages.length) return

  const tExtent = d3.extent(allStages, d => d.t)
  xScale.domain([new Date(tExtent[0]), new Date(tExtent[1] + 300000)])

  gX.call(d3.axisBottom(xS).ticks(6).tickFormat(d3.timeFormat('%H:%M'))).call(styleAxis)
  gY.call(d3.axisLeft(yScale)).call(styleAxis)

  const blockLayer = g.select('.block-layer')
  blockLayer.selectAll('*').remove()

  props.items.forEach((item) => {
    const segs = mergeSegments(item.analysis.sleep_stage_series || [])
    if (!segs.length) return

    segs.forEach(seg => {
      // Only draw stages that are in our band scale
      if (!stageOrder.includes(seg.stage)) return

      const x1 = xS(new Date(seg.startT))
      const x2 = xS(new Date(seg.endT))
      if (x2 <= 0 || x1 >= iw) return

      const clampX1 = Math.max(0, x1)
      const clampX2 = Math.min(iw, x2)
      const segW = clampX2 - clampX1
      if (segW < 0.5) return

      blockLayer.append('rect')
        .attr('x', clampX1)
        .attr('y', yScale(seg.stage))
        .attr('width', segW)
        .attr('height', yScale.bandwidth())
        .attr('fill', stageColors[seg.stage])
        .attr('rx', 2)
    })
  })
}

function update() { if (g) renderData() }

onMounted(() => {
  init(); update()
  resizeObs = new ResizeObserver(() => { init(); update() })
  resizeObs.observe(containerRef.value)
})
onBeforeUnmount(() => { resizeObs?.disconnect() })
watch(() => props.items, update, { deep: true })
</script>

<style scoped>
.chart-wrap { position: relative; }
.chart-container { width: 100%; }
.d3-tooltip {
  display: none;
  position: absolute;
  background: rgba(26,29,39,0.95);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 11px;
  color: var(--text);
  pointer-events: none;
  z-index: 10;
  white-space: nowrap;
}
</style>
