(function(root){
const buildings=Array.from({length:120},(_,i)=>({id:`B${String(i+1).padStart(3,'0')}`,x:90+(i%12)*110,y:70+Math.floor(i/12)*95,w:35+(i%3)*9,h:30+(i%4)*5}));
// Synthetic road is a vertical segment in a local metric coordinate system.
function distance(b){const dx=Math.max(b.x-700,700-b.x-b.w,0),dy=Math.max(120-b.y-b.h,b.y-900,0);return Math.hypot(dx,dy)}
function parse(text){
 if(/高度|人口|预测|路径|面积|密度|删除|之外|范围外|完全包含/.test(text))throw Error('当前仅支持道路缓冲区建筑物相交筛选，请移除高度、人口、预测或其他分析要求。');
 const m=text.trim().replace('半公里','0.5公里').match(/^(?:请)?(?:分析|查询|统计|筛选)示例路(?:周边|周围|附近)?\s*(\d+(?:\.\d+)?)\s*(米|m|公里|km)(?:范围)?(?:内)?(?:的)?建筑物[。！？]?$/i);
 if(!m)throw Error('请使用：分析示例路周边300米范围内的建筑物。当前只提供示例路，单次支持一个距离。');
 const radius=Number(m[1])*(/公里|km/i.test(m[2])?1000:1);
 if(radius<=0||radius>1000)throw Error('体验版距离需大于0且不超过1000米。');return radius;
}
function analyze(text){const radius=parse(text);return {text,radius,rows:buildings.map(b=>({...b,distance:distance(b),selected:distance(b)<=radius}))}}
const api={buildings,distance,parse,analyze};if(typeof module!=='undefined')module.exports=api;else root.geoai=api;
})(typeof window==='undefined'?globalThis:window);
