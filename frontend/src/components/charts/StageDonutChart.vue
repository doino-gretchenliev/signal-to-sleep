<template>
  <div class="stage-donut-wrap">
    <div class="donut-area">
      <div ref="containerRef" class="chart-container"></div>
    </div>
    <div class="stage-list">
      <div v-for="s in stageData" :key="s.stage" class="stage-row"
        @mouseenter="highlightStage(s.stage)"
        @mouseleave="unhighlightStage(s.stage)">
        <span class="row-dot" :style="{ backgroundColor: s.color }"></span>
        <span class="row-name">{{ s.label }}</span>
        <span class="row-dur">{{ s.duration }}</span>
        <span class="row-pct">{{ s.pct }}%</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import * as d3 from 'd3'
import { STAGES, STAGE_DOMAIN, STAGE_RANGE } from '../../utils/stageColors'

const props = defineProps({
  analyses: { type: Array, default: () => [] }
})

const containerRef = ref(null)

let svg, pie, arc, arcHover, color, resizeObserver = null
let width = 240, height = 240

// STAGES imported from stageColors.js

function mean(arr) { return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0 }
function fmtDur(m) {
  const h = Math.floor(m / 60), mm = Math.round(m % 60)
  return h > 0 ? `${h}h ${mm}m` : `${mm}m`
}

const stageData = computed(() => {
  const aa = props.analyses || []
  const vals = STAGES.map(st => ({ ...st, mins: mean(aa.map(a => a[st.field] || 0)) }))
  const total = vals.reduce((s, v) => s + v.mins, 0) || 1
  return vals.map(v => ({
    stage: v.key,
    label: v.label,
    color: v.color,
    minutes: v.mins,
    duration: fmtDur(v.mins),
    pct: ((v.mins / total) * 100).toFixed(1),
  }))
})

function highlightStage(stage) {
  if (!svg) return
  svg.selectAll('g.arc').each(function(d) {
    const el = d3.select(this).select('.arc-path')
    if (d.data.stage === stage) {
      el.transition().duration(200).attr('d', arcHover).attr('opacity', 1)
    } else {
      el.transition().duration(200).attr('opacity', 0.35)
    }
  })
}

function unhighlightStage() {
  if (!svg) return
  svg.selectAll('g.arc .arc-path')
    .transition().duration(200).attr('d', arc).attr('opacity', 0.85)
}

function initChart() {
  if (!containerRef.value) return
  const rect = containerRef.value.getBoundingClientRect()
  width = Math.min(rect.width || 240, 260)
  height = width
  const radius = Math.min(width, height) / 2 - 10

  d3.select(containerRef.value).selectAll('svg').remove()

  svg = d3.select(containerRef.value)
    .append('svg')
    .attr('width', width)
    .attr('height', height)

  svg.append('g')
    .attr('class', 'donut-g')
    .attr('transform', `translate(${width / 2},${height / 2})`)

  pie = d3.pie().value(d => d.minutes).sort(null)

  arc = d3.arc().innerRadius(radius * 0.6).outerRadius(radius)
  arcHover = d3.arc().innerRadius(radius * 0.6).outerRadius(radius * 1.12)

  color = d3.scaleOrdinal().domain(STAGE_DOMAIN).range(STAGE_RANGE)

  // Center text
  const g = svg.select('.donut-g')
  g.append('text').attr('class', 'center-label')
    .attr('text-anchor', 'middle').attr('dy', '0.1em')
    .attr('fill', '#e4e6f0').attr('font-size', '22px').attr('font-weight', 'bold')
  g.append('text').attr('class', 'center-sublabel')
    .attr('text-anchor', 'middle').attr('dy', '1.6em')
    .attr('fill', '#8b8fa3').attr('font-size', '11px').text('total sleep')
}

function updateChart() {
  if (!svg || !containerRef.value) return

  const data = stageData.value.filter(d => d.minutes > 0)
  const radius = Math.min(width, height) / 2 - 10
  arc.innerRadius(radius * 0.6).outerRadius(radius)
  arcHover.innerRadius(radius * 0.6).outerRadius(radius * 1.12)

  const g = svg.select('.donut-g')
  const pieData = pie(data)

  g.selectAll('g.arc').remove()

  const arcs = g.selectAll('g.arc')
    .data(pieData, d => d.data.stage)
    .enter()
    .append('g').attr('class', 'arc')

  arcs.append('path')
    .attr('class', 'arc-path')
    .attr('fill', d => color(d.data.stage))
    .attr('opacity', 0.85)
    .attr('stroke', 'rgba(26,29,39,0.6)')
    .attr('stroke-width', 1.5)
    .attr('d', arc)
    .on('mouseover', function(ev, d) {
      highlightStage(d.data.stage)
    })
    .on('mouseout', function() {
      unhighlightStage()
    })

  // Center text
  const totalMin = data.reduce((s, d) => s + d.minutes, 0)
  const hours = Math.floor(totalMin / 60), mins = Math.round(totalMin % 60)
  g.select('.center-label').text(hours > 0 ? `${hours}h ${mins}m` : `${mins}m`)
}

onMounted(() => {
  initChart()
  updateChart()
  resizeObserver = new ResizeObserver(() => {
    initChart()
    updateChart()
  })
  resizeObserver.observe(containerRef.value)
})

onBeforeUnmount(() => { resizeObserver?.disconnect() })
watch(() => props.analyses, updateChart, { deep: true })
</script>

<style scoped>
.stage-donut-wrap {
  display: flex;
  align-items: center;
  gap: 24px;
  width: 100%;
}
.donut-area {
  flex-shrink: 0;
  padding: 14px;
}
.chart-container {
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: visible;
}
.chart-container :deep(svg) {
  overflow: visible;
}
.stage-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  flex: 1;
  min-width: 0;
}
.stage-row {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--surface2, rgba(255,255,255,0.04));
  border-radius: 8px;
  padding: 10px 14px;
  cursor: pointer;
  transition: background 0.2s;
}
.stage-row:hover {
  background: rgba(255,255,255,0.08);
}
.row-dot {
  width: 12px;
  height: 12px;
  border-radius: 3px;
  flex-shrink: 0;
}
.row-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  min-width: 50px;
}
.row-dur {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin-left: auto;
}
.row-pct {
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
  min-width: 48px;
  text-align: right;
}
</style>
