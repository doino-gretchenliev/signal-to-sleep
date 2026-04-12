<template>
  <div class="chart-wrap">
    <div ref="containerRef" class="chart-container"></div>
    <div class="chart-legend">
      <template v-if="items.length === 1">
        <span class="leg-item"><span class="leg-bar" style="background:#a78bfa"></span>Noise Level</span>
        <span class="leg-item"><span class="leg-dash" style="border-color:#8b8fa3"></span>Average</span>
        <span class="leg-item"><span class="leg-zone" style="background:rgba(251,191,36,0.3)"></span>Loud</span>
        <button class="stage-toggle" :class="{ active: showStages }" @click="toggleStages">
          <span class="stage-icon"></span>Sleep Stages
        </button>
      </template>
      <template v-else>
        <span v-for="(item, i) in items" :key="i" class="leg-item">
          <span class="leg-bar" :style="{ background: palette[i % palette.length] }"></span>
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
const showStages = ref(true)
const palette = ['#a78bfa','#60a5fa','#34d399','#f87171','#fbbf24','#f472b6','#38bdf8','#fb923c']
const stageColors = STAGE_COLORS

function toggleStages() { showStages.value = !showStages.value; update() }

const STRIP_H = 14
const M = { top: 16 + STRIP_H + 4, right: 16, bottom: 28, left: 44 }
let svg, g, rootG, xScale, yScale, gX, gY, resizeObs, w = 600, h = 260

// Noise level thresholds in dBFS
const LOUD_THRESHOLD = -25 // above this is "loud" (potential snoring / disturbance)

function periodLabel(p) {
  const d = new Date(p.started_at)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + p.sleep_type
}

function downsample(data, maxPts) {
  if (data.length <= maxPts) return data
  const out = [data[0]]
  const bucketSize = (data.length - 2) / (maxPts - 2)
  let a = 0
  for (let i = 1; i < maxPts - 1; i++) {
    const rangeStart = Math.floor((i - 1) * bucketSize) + 1
    const rangeEnd = Math.min(Math.floor(i * bucketSize) + 1, data.length)
    const nextStart = Math.floor(i * bucketSize) + 1
    const nextEnd = Math.min(Math.floor((i + 1) * bucketSize) + 1, data.length)
    let avgT = 0, avgV = 0, count = 0
    for (let j = nextStart; j < nextEnd; j++) { avgT += data[j].t; avgV += data[j].v; count++ }
    avgT /= count; avgV /= count
    let maxArea = -1, maxIdx = rangeStart
    for (let j = rangeStart; j < rangeEnd; j++) {
      const area = Math.abs((data[a].t - avgT) * (data[j].v - data[a].v) - (data[a].t - data[j].t) * (avgV - data[a].v))
      if (area > maxArea) { maxArea = area; maxIdx = j }
    }
    out.push(data[maxIdx])
    a = maxIdx
  }
  out.push(data[data.length - 1])
  return out
}

function styleAxis(sel) {
  sel.selectAll('text').attr('fill', '#8b8fa3').attr('font-size', '11px')
  sel.selectAll('line,path').attr('stroke', '#2a2e3d')
}

function init() {
  if (!containerRef.value) return
  d3.select(containerRef.value).selectAll('svg').remove()
  const rect = containerRef.value.getBoundingClientRect()
  w = Math.max(rect.width || 600, 300); h = 260
  const iw = w - M.left - M.right, ih = h - M.top - M.bottom

  svg = d3.select(containerRef.value).append('svg').attr('width', w).attr('height', h)

  const clipId = 'noise-clip-' + Math.random().toString(36).slice(2, 8)
  svg.append('defs').append('clipPath').attr('id', clipId)
    .append('rect').attr('width', iw).attr('height', ih)

  // Stage strip at top
  svg.append('g').attr('class', 'stage-strip')
    .attr('transform', `translate(${M.left},${16})`)

  rootG = svg.append('g').attr('transform', `translate(${M.left},${M.top})`)
  g = rootG.append('g').attr('clip-path', `url(#${clipId})`)

  xScale = d3.scaleTime().range([0, iw])
  yScale = d3.scaleLinear().range([ih, 0])

  g.append('g').attr('class', 'grid')
  g.append('g').attr('class', 'threshold-layer')
  g.append('g').attr('class', 'data-layer')
  g.append('g').attr('class', 'avg-layer')

  const ch = rootG.append('g').attr('class', 'crosshair').style('display', 'none')
  ch.append('line').attr('y1', 0).attr('y2', ih).attr('stroke', '#7c6ef0').attr('stroke-dasharray', '3,3').attr('stroke-width', 1)

  gX = rootG.append('g').attr('transform', `translate(0,${ih})`)
  gY = rootG.append('g')

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
    const [mx] = d3.pointer(ev, rootG.node())
    if (mx >= 0 && mx <= iw) {
      ch.style('display', null).attr('transform', `translate(${mx},0)`)
      const tip = tooltipEl.value
      if (tip) {
        tip.style.display = 'block'
        tip.style.left = (ev.offsetX + 12) + 'px'
        tip.style.top = (ev.offsetY - 10) + 'px'
        const t = xScale.invert(mx)
        // Find nearest data point
        const allData = props.items.flatMap(it => it.analysis.noise_series || [])
        let nearest = null, minDist = Infinity
        for (const d of allData) {
          const dist = Math.abs(new Date(d.t) - t)
          if (dist < minDist) { minDist = dist; nearest = d }
        }
        if (nearest) {
          tip.textContent = `${d3.timeFormat('%H:%M:%S')(t)}  ${nearest.v} dBFS`
        } else {
          tip.textContent = d3.timeFormat('%H:%M')(t)
        }
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
  const allData = props.items.flatMap(it => it.analysis.noise_series || [])
  if (!allData.length) return

  const tExtent = d3.extent(allData, d => d.t)
  const vExtent = d3.extent(allData, d => d.v)
  xScale.domain([new Date(tExtent[0]), new Date(tExtent[1])])
  // dBFS range: typically -60 to 0
  yScale.domain([Math.min(-60, (vExtent[0] || -60) - 2), Math.max(0, (vExtent[1] || 0) + 2)]).nice()

  gX.call(d3.axisBottom(xS).ticks(6).tickFormat(d3.timeFormat('%H:%M'))).call(styleAxis)
  gY.call(d3.axisLeft(yScale).ticks(5).tickFormat(d => `${d}`)).call(styleAxis)

  // Grid
  g.select('.grid').selectAll('line').remove()
  g.select('.grid').selectAll('line').data(yScale.ticks(5)).enter().append('line')
    .attr('x1', 0).attr('x2', iw).attr('y1', d => yScale(d)).attr('y2', d => yScale(d))
    .attr('stroke', 'rgba(255,255,255,0.05)')

  // Stage strip
  const strip = svg.select('.stage-strip')
  strip.selectAll('*').remove()
  if (single && showStages.value) {
    const stages = props.items[0].analysis.sleep_stage_series || []
    if (stages.length) {
      const sorted = [...stages].sort((a, b) => a.t - b.t)
      const sExtent = d3.extent(sorted, d => d.t)
      const stripX = d3.scaleTime().domain([new Date(sExtent[0]), new Date(sExtent[1])]).range([0, iw])
      for (let i = 0; i < sorted.length; i++) {
        const s = sorted[i], nextT = sorted[i + 1]?.t || sExtent[1]
        const x1 = stripX(new Date(s.t)), x2 = stripX(new Date(nextT))
        strip.append('rect')
          .attr('x', Math.max(0, x1)).attr('width', Math.min(iw, x2) - Math.max(0, x1))
          .attr('y', 0).attr('height', STRIP_H)
          .attr('fill', stageColors[s.stage] || 'transparent')
          .attr('rx', 1)
      }
      strip.append('rect')
        .attr('x', 0).attr('y', 0).attr('width', iw).attr('height', STRIP_H)
        .attr('fill', 'none').attr('stroke', '#2a2e3d').attr('rx', 3)
    }
  }

  // Loud threshold zone
  const threshLayer = g.select('.threshold-layer')
  threshLayer.selectAll('*').remove()
  const threshY = yScale(LOUD_THRESHOLD)
  if (threshY > 0 && threshY < ih) {
    threshLayer.append('rect')
      .attr('x', 0).attr('y', 0).attr('width', iw).attr('height', threshY)
      .attr('fill', 'rgba(251,191,36,0.06)')
    threshLayer.append('line')
      .attr('x1', 0).attr('x2', iw).attr('y1', threshY).attr('y2', threshY)
      .attr('stroke', 'rgba(251,191,36,0.3)').attr('stroke-dasharray', '4,4').attr('stroke-width', 1)
    threshLayer.append('text')
      .attr('x', iw - 4).attr('y', threshY - 5)
      .attr('fill', 'rgba(251,191,36,0.6)').attr('font-size', '9px').attr('text-anchor', 'end')
      .text('Loud')
  }

  const maxPts = Math.max(300, iw)
  const dataLayer = g.select('.data-layer')
  dataLayer.selectAll('*').remove()

  if (single) {
    const raw = props.items[0].analysis.noise_series || []
    const data = downsample(raw, maxPts)
    // Area chart with bars for loud sections
    const area = d3.area()
      .x(d => xS(new Date(d.t)))
      .y0(ih)
      .y1(d => yScale(d.v))
      .curve(d3.curveMonotoneX)

    const line = d3.line()
      .x(d => xS(new Date(d.t)))
      .y(d => yScale(d.v))
      .curve(d3.curveMonotoneX)

    // Fill area
    dataLayer.append('path').datum(data).attr('d', area)
      .attr('fill', 'rgba(167,139,250,0.15)')

    // Stroke line
    dataLayer.append('path').datum(data).attr('d', line)
      .attr('fill', 'none').attr('stroke', '#a78bfa').attr('stroke-width', 1.5).attr('opacity', 0.9)

    // Highlight loud points
    data.filter(d => d.v > LOUD_THRESHOLD).forEach(d => {
      const cx = xS(new Date(d.t)), cy = yScale(d.v)
      if (cx >= 0 && cx <= iw) {
        dataLayer.append('circle').attr('cx', cx).attr('cy', cy).attr('r', 3)
          .attr('fill', '#fbbf24').attr('opacity', 0.8)
      }
    })
  } else {
    const line = d3.line().x(d => xS(new Date(d.t))).y(d => yScale(d.v)).curve(d3.curveMonotoneX)
    props.items.forEach((item, i) => {
      const raw = item.analysis.noise_series || []
      const data = downsample(raw, maxPts)
      dataLayer.append('path').datum(data).attr('d', line)
        .attr('fill', 'none').attr('stroke', palette[i % palette.length]).attr('stroke-width', 1.5).attr('opacity', 0.8)
    })
  }

  // Avg line
  const avgLayer = g.select('.avg-layer')
  avgLayer.selectAll('*').remove()
  const avgVal = d3.mean(allData, d => d.v)
  if (avgVal != null) {
    avgLayer.append('line').attr('x1', 0).attr('x2', iw)
      .attr('y1', yScale(avgVal)).attr('y2', yScale(avgVal))
      .attr('stroke', 'rgba(255,255,255,0.4)').attr('stroke-dasharray', '6,4').attr('stroke-width', 1)
    avgLayer.append('text').attr('x', iw - 4).attr('y', yScale(avgVal) - 5)
      .attr('fill', 'rgba(255,255,255,0.5)').attr('font-size', '10px').attr('text-anchor', 'end')
      .text(`avg ${Math.round(avgVal)} dBFS`)
  }
}

function update() { if (g) render() }

onMounted(() => { init(); update(); resizeObs = new ResizeObserver(() => { init(); update() }); resizeObs.observe(containerRef.value) })
onBeforeUnmount(() => { resizeObs?.disconnect() })
watch(() => props.items, update, { deep: true })
</script>

<style scoped>
.chart-wrap { position: relative; }
.chart-container { width: 100%; height: 260px; }
.chart-legend { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 8px; }
.leg-item { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-dim); }
.leg-bar { width: 10px; height: 12px; border-radius: 2px; }
.leg-dash { width: 16px; height: 0; border-top: 2px dashed; }
.leg-zone { width: 14px; height: 12px; border-radius: 2px; }
.d3-tooltip { display: none; position: absolute; background: rgba(26,29,39,0.95); border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; font-size: 11px; color: var(--text); pointer-events: none; z-index: 10; white-space: nowrap; }
.stage-toggle { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-dim); background: transparent; border: 1px solid var(--border); border-radius: 6px; padding: 3px 10px; cursor: pointer; margin-left: auto; transition: all 0.2s; }
.stage-toggle:hover { border-color: var(--accent); color: var(--text); }
.stage-toggle.active { background: rgba(124,110,240,0.15); border-color: var(--accent); color: var(--accent); }
.stage-icon { width: 10px; height: 10px; border-radius: 2px; background: linear-gradient(135deg, #3b82f6 0%, #2dd4bf 50%, #e879f9 100%); }
</style>
