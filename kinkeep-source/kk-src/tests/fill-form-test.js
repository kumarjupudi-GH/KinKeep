const { chromium } = require('playwright');
const T = [
 ['assets','Savings account at HDFC in India, Priya, 450,000 rupees, statement dated Oct 20', {name:'HDFC savings account',type:'Bank',owner:'Priya',country:'IN',currency:'INR',value:'450000',source:'Statement'}],
 ['assets','House in Hyderabad worth 85 lakh, owned by Arun, appraisal March 5 2026', {type:'Real estate',owner:'Arun',currency:'INR',value:'8500000',source:'Appraisal'}],
 ['assets','Fidelity brokerage account balance of $52,300 for Priya as of Oct 1', {name:'Fidelity brokerage account',type:'Investment',owner:'Priya',currency:'USD',value:'52300'}],
 ['assets','Arun 401(k) at Vanguard, $184,500 statement','{"type":"Retirement","owner":"Arun","value":"184500"}'],
 ['assets','Name: Gold coins; Type: Gold; Owner: Priya; Value: 12,000; Currency: USD', {name:'Gold coins',type:'Gold',owner:'Priya',value:'12000',currency:'USD'}],
 ['assets','2019 Honda Accord, Arun, about $17,500', {type:'Vehicle',owner:'Arun',value:'17500',source:'Estimate'}],
 ['liabs','Car loan from Chase for Arun, balance $9,800, 5.4% interest, $410 a month, due Nov 12', {name:'Chase car loan',type:'Loan',owner:'Arun',balance:'9800',rate:'5.4',payment:'410'}],
 ['liabs','Home mortgage with Wells Fargo, we owe 312,000 at 6.25%, monthly payment of $2,150, due on the 1st', {type:'Mortgage',balance:'312000',rate:'6.25',payment:'2150'}],
 ['liabs','Credit card with Amex, Priya, outstanding $3,200, minimum payment $95, 22% APR, due Nov 20', {type:'Credit card',owner:'Priya',balance:'3200',rate:'22',payment:'95'}],
 ['liabs','Education loan SBI for Dev, 4 lakh remaining, EMI 12,500 per month', {type:'Loan',owner:'Dev',balance:'400000',payment:'12500',currency:'INR'}],
 ['policies','Umbrella policy with Cedar Mutual for Arun and Priya, coverage $1,000,000, deductible $500, renews March 2, beneficiary Priya Nair', {kind:'Umbrella',name:'Cedar Mutual Umbrella',holder:'Arun and Priya',limit:'$1,000,000',deductible:'$500',beneficiary:'Priya Nair'}],
 ['policies','Term life insurance from Northwestern Mutual, Arun, 750,000 coverage, beneficiary Priya Nair, renews Aug 15 2027, claims 1-800-555-0177', {kind:'Life',holder:'Arun',limit:'$750,000',beneficiary:'Priya Nair',claims:'1-800-555-0177'}],
 ['policies','Health insurance Aetna family plan, deductible $2,500, premium $620 monthly, renews Jan 1', {kind:'Health',deductible:'$2,500'}],
 ['policies','Type: Auto; Insurer: State Farm; Covered person: Arun; Limit: 100/300/100; Deductible: $500; Renews: Nov 19', {kind:'Auto',name:'State Farm',holder:'Arun',limit:'100/300/100',deductible:'$500'}],
];
(async()=>{const b=await chromium.launch();const p=await (await b.newContext({viewport:{width:1280,height:1000}})).newPage();const errs=[];p.on('pageerror',e=>errs.push(e.message));
await p.goto('file://'+process.cwd()+'/dist/KinKeep.html');await p.waitForTimeout(400);await p.click('[data-g=explore]');await p.waitForTimeout(300);
const nav={assets:['fin','assets'],liabs:['fin','liab'],policies:['fin','cover']};
let bad=0;
for (const [coll,text,exp] of T) {
  if (typeof exp==='string') continue;
  await p.click('[data-grp=fin]').catch(()=>{}); await p.evaluate(([c])=>{},[coll]);
  const [g,n]=nav[coll]; if(!(await p.isVisible('[data-nav='+n+']')))await p.click('[data-grp='+g+']'); await p.click('[data-nav='+n+']');await p.waitForTimeout(150);
  await p.fill('#qa-'+coll,text);await p.waitForTimeout(350);
  const live=await p.textContent('#qa-live-'+coll);
  await p.click('[data-act=qa-fill][data-coll='+coll+']');await p.waitForTimeout(250);
  const got=await p.evaluate(c=>{const f=document.querySelector('form[data-coll='+c+']');const o={};[...f.elements].forEach(e=>{if(e.name)o[e.name]=e.value});return o},coll);
  const diffs=Object.keys(exp).filter(k=>String(got[k])!==exp[k]).map(k=>k+': want "'+exp[k]+'" got "'+got[k]+'"');
  if(diffs.length)bad++;
  console.log((diffs.length?'FAIL ':'PASS ')+coll+' | '+text.slice(0,60)+(diffs.length?'\n     '+diffs.join('\n     ')+'\n     all: '+JSON.stringify(got):'')+(live?'':'  [no live preview]'));
}
console.log('failures',bad,'errors',JSON.stringify(errs));await b.close();})();
