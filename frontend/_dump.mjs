import * as echarts from 'echarts'
import { valueAxis, catAxis, gridFor, bottomLegend } from './src/utils/chartTheme.js'
const W=500,H=320
const BUS=['集团总部','劳务事业部','运输事业部','自营事业部','阔展事业部','多式联运事业部','供应链事业部']
const c=echarts.init(null,null,{renderer:'svg',ssr:true,width:W,height:H})
c.setOption({legend:bottomLegend(),grid:gridFor(BUS,{nameTop:true}),xAxis:catAxis(BUS),yAxis:valueAxis({name:'达成率%',formatter:'{value}%'}),series:[{type:'bar',name:'YTD收入达成',data:[80,95,110,60,130,45,88]}]})
const svg=c.renderToSVGString()
import fs from 'fs'
fs.writeFileSync('/tmp/chart.svg', svg)
const texts=[...svg.matchAll(/<text\b([^>]*)>([\s\S]*?)<\/text>/g)]
console.log('TOTAL text nodes:', texts.length, 'svgLen:', svg.length)
