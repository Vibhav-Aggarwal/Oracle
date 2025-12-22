let pnlChart=null,distributionChart=null;const INITIAL_BALANCE=1000;let currentMode='paper';
document.addEventListener("DOMContentLoaded",()=>{initCharts();loadMode();refreshData();setInterval(refreshData,5000);setInterval(updateTime,1000)});

function initCharts(){
const pnlCtx=document.getElementById("pnlChart").getContext("2d");
pnlChart=new Chart(pnlCtx,{type:"line",data:{labels:[],datasets:[{label:"P&L",data:[],borderColor:"#5e72e4",backgroundColor:"rgba(94,114,228,0.1)",borderWidth:2,fill:true,tension:0.4,pointRadius:0}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{color:"rgba(255,255,255,0.05)"},ticks:{color:"#5c5c6d"}},y:{grid:{color:"rgba(255,255,255,0.05)"},ticks:{color:"#5c5c6d",callback:function(v){return"$"+v}}}}}});
const distCtx=document.getElementById("distributionChart").getContext("2d");
distributionChart=new Chart(distCtx,{type:"doughnut",data:{labels:["Wins","Losses"],datasets:[{data:[0,0],backgroundColor:["#00d97e","#f5365c"],borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,cutout:"70%",plugins:{legend:{display:false}}}});
}

async function loadMode(){
try{const r=await fetch("/api/mode");const d=await r.json();currentMode=d.mode||"paper";updateModeUI(currentMode)}catch(e){console.error(e)}
}

function updateModeUI(mode){
currentMode=mode;
document.getElementById("mode-paper").classList.toggle("active",mode==="paper");
document.getElementById("mode-live").classList.toggle("active",mode==="live");
document.getElementById("mode-label").textContent=mode==="live"?"LIVE TRADING":"Paper Trading";
document.body.style.setProperty("--header-glow",mode==="live"?"rgba(0,217,126,0.1)":"transparent");
}

function switchMode(mode){
if(mode===currentMode)return;
if(mode==="live"){document.getElementById("modal-overlay").classList.add("show")}
else{setMode("paper")}
}

function closeModal(){document.getElementById("modal-overlay").classList.remove("show")}

function confirmLiveMode(){closeModal();setMode("live")}

async function setMode(mode){
try{
const r=await fetch("/api/mode",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({mode:mode})});
const d=await r.json();
if(d.success){updateModeUI(mode);refreshData()}
}catch(e){console.error(e)}
}

async function refreshData(){
try{
const[statusRes,tradesRes,pnlRes]=await Promise.all([fetch("/api/status"),fetch("/api/trades"),fetch("/api/pnl-history")]);
const status=await statusRes.json(),trades=await tradesRes.json(),pnlHistory=await pnlRes.json();
if(status.mode)updateModeUI(status.mode);
updateStatus(status);updatePositions(status.positions);updateTrades(trades);updatePnlChart(pnlHistory);updateDistributionChart(trades);
}catch(e){console.error("Error:",e)}
}

function updateStatus(s){
const balance=s.balance||INITIAL_BALANCE;
const balanceChange=(balance-INITIAL_BALANCE)/INITIAL_BALANCE*100;
document.getElementById("balance").textContent="$"+balance.toFixed(2);
const bce=document.getElementById("balance-change");
bce.textContent=(balanceChange>=0?"+":"")+balanceChange.toFixed(2)+"%";
bce.className="stat-change "+(balanceChange>=0?"positive":"negative");
const pnl=s.metrics?s.metrics.total_pnl:0;
document.getElementById("total-pnl").textContent="$"+(pnl||0).toFixed(2);
document.getElementById("pnl-trades").textContent=(s.metrics?s.metrics.total_trades:0)+" trades";
document.getElementById("win-rate").textContent=(s.metrics?s.metrics.win_rate:0)+"%";
document.getElementById("profit-factor").textContent="PF: "+(s.metrics?s.metrics.profit_factor:0);
const posLen=(s.positions||[]).length;
document.getElementById("open-positions").textContent=posLen;
document.getElementById("positions-count").textContent=posLen;
document.getElementById("fees-paid").textContent="Fees: $"+(s.metrics?s.metrics.fees_paid:0).toFixed(2);
updateSvc("bot-status",s.services?s.services.oracle_bot:false);
updateSvc("data-status",s.services?s.services.data_puller:false);
updateSvc("healer-status",s.services?s.services.autohealer:false);
document.getElementById("last-update").querySelector("span:last-child").textContent=new Date().toLocaleTimeString();
}

function updateSvc(id,active){document.getElementById(id).className="status-item "+(active?"active":"inactive")}

function updatePositions(pos){
const tb=document.getElementById("positions-body");
if(!pos||!pos.length){tb.innerHTML="<tr class=\"empty-row\"><td colspan=\"8\">No active positions</td></tr>";return}
let html="";
for(let i=0;i<pos.length;i++){
const p=pos[i];const pnl=p.unrealized_pnl||0;
const side=(p.side||"long").toLowerCase();
html+="<tr><td>"+(p.exchange||"?")+"</td><td><strong>"+(p.symbol||"")+"</strong></td>";
html+="<td><span class=\"side-badge "+side+"\">"+(p.side||"LONG").toUpperCase()+"</span></td>";
html+="<td>$"+(p.entry_price||0).toFixed(4)+"</td><td>$"+(p.current_price||p.entry_price||0).toFixed(4)+"</td>";
html+="<td>$"+(p.size_usd||0).toFixed(2)+"</td>";
html+="<td><span class=\"pnl-value "+(pnl>=0?"positive":"negative")+"\">"+(pnl>=0?"+":"")+"$"+pnl.toFixed(2)+"</span></td>";
html+="<td><span style=\"color:#f5365c\">SL: $"+(p.stop_loss||0).toFixed(4)+"</span><br><span style=\"color:#00d97e\">TP: $"+(p.take_profit||0).toFixed(4)+"</span></td></tr>";
}
tb.innerHTML=html;
}

function updateTrades(trades){
const tb=document.getElementById("trades-body");
if(!trades||!trades.length){tb.innerHTML="<tr class=\"empty-row\"><td colspan=\"8\">No trades yet</td></tr>";return}
let html="";
const list=trades.slice(0,20);
for(let i=0;i<list.length;i++){
const t=list[i];const pnl=t.pnl||0;
const time=new Date(t.timestamp||Date.now()).toLocaleString();
const side=(t.side||"long").toLowerCase();
html+="<tr><td>"+time+"</td><td>"+(t.exchange||"?")+"</td><td><strong>"+(t.symbol||"")+"</strong></td>";
html+="<td><span class=\"side-badge "+side+"\">"+(t.side||"LONG").toUpperCase()+"</span></td>";
html+="<td>$"+(t.entry_price||0).toFixed(4)+"</td><td>$"+(t.exit_price||0).toFixed(4)+"</td>";
html+="<td><span class=\"pnl-value "+(pnl>=0?"positive":"negative")+"\">"+(pnl>=0?"+":"")+"$"+pnl.toFixed(2)+"</span></td>";
html+="<td>"+(t.exit_reason||"--")+"</td></tr>";
}
tb.innerHTML=html;
}

function updatePnlChart(h){
if(!h||!h.length){pnlChart.data.labels=["Start"];pnlChart.data.datasets[0].data=[0];pnlChart.update("none");return}
const labels=[],data=[];
for(let i=0;i<h.length;i++){labels.push(new Date(h[i].timestamp).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}));data.push(h[i].pnl)}
pnlChart.data.labels=labels;pnlChart.data.datasets[0].data=data;
const last=h[h.length-1]?h[h.length-1].pnl:0;
pnlChart.data.datasets[0].borderColor=last>=0?"#00d97e":"#f5365c";
pnlChart.update("none");
}

function updateDistributionChart(trades){
if(!trades||!trades.length){distributionChart.data.datasets[0].data=[0,1];distributionChart.update("none");document.getElementById("wins-count").textContent="0";document.getElementById("losses-count").textContent="0";return}
let w=0,l=0;
for(let i=0;i<trades.length;i++){if((trades[i].pnl||0)>0)w++;else if((trades[i].pnl||0)<0)l++}
distributionChart.data.datasets[0].data=[w,l];distributionChart.update("none");
document.getElementById("wins-count").textContent=w;document.getElementById("losses-count").textContent=l;
}

function updateTime(){document.getElementById("server-time").textContent=new Date().toLocaleString()}

// Expose functions to global scope for onclick handlers
window.switchMode=switchMode;
window.closeModal=closeModal;
window.confirmLiveMode=confirmLiveMode;
