<script setup>
import {ref,onMounted,onBeforeUnmount,watch} from 'vue'
import {use,init,registerMap} from 'echarts/core'
import {MapChart, BarChart} from 'echarts/charts'
import {GridComponent, TooltipComponent, VisualMapComponent, GeoComponent} from 'echarts/components'
import {CanvasRenderer} from 'echarts/renderers'
import outlines from './assets/provinces.json'
use([MapChart,BarChart,GridComponent,TooltipComponent,VisualMapComponent,GeoComponent,CanvasRenderer])
registerMap('atlas31',outlines)
const props=defineProps({options:Object,label:String})
const emit=defineEmits(['pick'])
const el=ref(null)
let chart, observer
onMounted(()=>{
  chart=init(el.value)
  chart.setOption(props.options)
  chart.on('click',e=>{if(e.data?.regionKey) emit('pick',e.data.regionKey)})
  observer=new ResizeObserver(()=>{
    const node=el.value
    if(!node?.isConnected || !chart || !node.clientWidth || !node.clientHeight) return
    if(node.clientWidth!==chart.getWidth() || node.clientHeight!==chart.getHeight()) chart.resize()
  })
  observer.observe(el.value)
})
watch(()=>props.options, opt=>chart?.setOption(opt,true))
onBeforeUnmount(()=>{observer?.disconnect();chart?.dispose();chart=null})
</script>
<template><div class="echart" ref="el" role="img" :aria-label="label"></div></template>
