<template>
  <div class="chart-wrap">
    <div ref="containerRef" class="chart-container"></div>
    <div class="chart-legend">
      <template v-if="items.length === 1">
        <span v-for="s in ['awake','rem','light','deep']" :key="s" class="leg-item">
          <span class="leg-block" :style="{ background: stageColors[s] }"></span>{{ s.charAt(0).toUpperCase() + s.slice(1) }}
        </span>
      </template>
      <template v-else>
        <span v-for="(item, i) in items" :key="i" class="leg-item">
          <span class="leg-line" :style="{ background: palette[i % palette.length] }"></span>
          {{ periodLabel(item.period) }}
        </span>
      </template>
    </div>
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
const palette = ['#f87171','#60a5fa','#34d399','#a78bfa','#fbbf24','#f472b6','#38bdf8','#fb923c']
const stageColors = STAGE_COLORS
const stageOrder = ['deep', 'light', 'rem', 'awake']
const stageY = { deep: 0, light: 1, rem: 2, awake: 3 }

const M = { top: 16, right: 16, bottom: 28, left: 64 }
let svg, g, xScale, yScale, gX, gY, resizeObs, w = 600, h = 200

function periodLabel(p) {
  const d = new Date(p.started_at)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + p.sleep_type
}

function buildSegments(stages) {
  if (!stages.length) return []
  const sorted = [...stages].sort((a, b) => a.t - b.t)
  const segs = []
  for (let i = 0; i < sorted.length; i++) {
    const cur = sorted[i]
    const nextT = sorted[i + 1]?.t || cur.t + 300000
    segs.push({ stage: cur.stage, startT: cur.t, endT: nextT })
  }
  return segs
}

function styleAxis(sel) {
  sel.selectAll('text').attr('fill', '#8b8fa3').attr('font-size', '11px')
  sel.selectAll('line,path').attr('stroke', '#2a2e3d')
}

function init() {
  if (!containerRef.value) return
  d3.select(containerRef.value).selectAll('svg').remove()
  const rect = containerRef.value.getBoundingClientRect()
  w = Math.max(rect.width || 600, 300); h = 200
  const iw = w - M.left - M.right, ih = h - M.top - M.bottom

  svg = d3.select(containerRef.value).append('svg').attr('width', w).attr('height', h)
  g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`)

  xScale = d3.scaleTime().range([0, iw])
  yScale = d3.scaleBand().domain(stageOrder).range([ih, 0]).padding(0.15)

  g.append('g').attr('class', 'data-layer')

  const ch = g.append('g').attr('class', 'crosshair').style('display', 'none')
  ch.append('line').attr('y1', 0).attr('y2', ih).attr('stroke', '#7c6ef0').attr('stroke-dasharray', '3,3').attr('stroke-width', 1)

  gX = g.append('g').attr('transform', `translate(0,${ih})`)
  gY = g.append('g')

  const zoom = d3.zoom().scaleExtent([1, 20])
    .extent([[M.left, M.top], [M.left + iw, M.top + ih]])
    .translateExtent([[M.left, M.top], [M.left + iw, M.top + ih]])
    .on('zoom', ev => {
      const nx = ev.transform.rescaleX(xScale)
      gX.call(d3.axisBottom(nx).ticks(6).tickFormat(d3.timeFormat('%H:%M'))).call(styleAxis)
      render(nx)
    })
  svg.call(zoom)
  svg.on('dblclick.zoom', () => svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity))

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
        // Find stage at this time
        const allSegs = props.items.flatMap(it => buildSegments(it.analysis.sleep_stage_series || []))
        const tMs = t.getTime()
        const seg = allSegs.find(s => tMs >= s.startT && tMs < s.endT)
        tip.textContent = d3.timeFormat('%H:%M')(t) + (seg ? ` — ${seg.stage}` : '')
      }
    }
  })
  svg.on('mouseleave', () => {
    ch.style('display', 'none')
    if (tooltipEl.value) tooltipEl.value.style.display = 'none'
  })
}

function render(xS) {
  if (!g) return
  xS = xS || xScale
  const iw = w - M.left - M.right, ih = h - M.top - M.bottom
  const single = props.items.length === 1
  const allData = props.items.flatMap(it => it.analysis.sleep_stage_series || [])
  if (!allData.length) return

  const tExtent = d3.extent(allData, d => d.t)
  xScale.domain([new Date(tExtent[0]), new Date(tExtent[1])])

  gX.call(d3.axisBottom(xS).ticks(6).tickFormat(d3.timeFormat('%H:%M'))).call(styleAxis)
  gY.call(d3.axisLeft(yScale).tickFormat(s => s.charAt(0).toUpperCase() + s.slice(1))).call(styleAxis)

  const dataLayer = g.select('.data-layer')
  dataLayer.selectAll('*').remove()

  if (single) {
    const stages = props.items[0].analysis.sleep_stage_series || []
    const segs = buildSegments(stages)
    segs.forEach(seg => {
      const x1 = xS(new Date(seg.startT)), x2 = xS(new Date(seg.endT))
      if (x2 > 0 && x1 < iw) {
        dataLayer.append('rect')
          .attr('x', Math.max(0, x1))
          .attr('width', Math.min(iw, x2) - Math.max(0, x1))
          .attr('y', yScale(seg.stage))
          .attr('height', yScale.bandwidth())
          .attr('fill', stageColors[seg.stage] || '#666')
          .attr('opacity', 0.8)
          .attr('rx', 2)
      }
    })
  } else {
    // Multi-period: stepped lines
    props.items.forEach((item, i) => {
      const stages = item.analysis.sleep_stage_series || []
      const segs = buildSegments(stages)
      const color = palette[i % palette.length]
      const points = []
      segs.forEach(seg => {
        const yMid = yScale(seg.stage) + yScale.bandwidth() / 2
        points.push({ t: seg.startT, y: yMid })
        points.push({ t: seg.endT, y: yMid })
      })
      const lineGen = d3.line().x(d => xS(new Date(d.t))).y(d => d.y).curve(d3.curveStepAfter)
      dataLayer.append('path').datum(points).attr('d', lineGen)
        .attr('fill', 'none').attr('stroke', color).attr('stroke-width', 2).attr('opacity', 0.7)
    })
  }
}

function update() { if (g) render() }

onMounted(() => { init(); update(); resizeObs = new ResizeObserver(() => { init(); update() }); resizeObs.observe(containerRef.value) })
onBeforeUnmount(() => { resizeObs?.disconnect() })
watch(() => props.items, update, { deep: true })
</script>

<style scoped>
.chart-wrap { position: relative; }
.chart-container { width: 100%; height: 200px; }
.chart-legend { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 8px; }
.leg-item { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-dim); }
.leg-line { width: 16px; height: 3px; border-radius: 2px; }
.leg-block { width: 14px; height: 10px; border-radius: 3px; }
.d3-tooltip { display: none; position: absolute; background: rgba(26,29,39,0.95); border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; font-size: 11px; color: var(--text); pointer-events: none; z-index: 10; white-space: nowrap; }
</style>
