/* Inclusive date ranges shared by the local file and optional server browser. */
(function(root){
  const iso=d=>d.toISOString().slice(0,10);
  const parse=s=>{if(!/^\d{4}-\d{2}-\d{2}$/.test(s))throw Error('Use a valid date.');const d=new Date(s+'T00:00:00Z');if(!Number.isFinite(+d)||iso(d)!==s)throw Error('Use a valid date.');return d;};
  const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/Chicago',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  function shift(s,months){const d=parse(s),day=d.getUTCDate();d.setUTCDate(1);d.setUTCMonth(d.getUTCMonth()+months);const max=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,0)).getUTCDate();d.setUTCDate(Math.min(day,max));return iso(d);}
  function addDays(s,n){const d=parse(s);d.setUTCDate(d.getUTCDate()+n);return iso(d);}
  function range(start,end){if(start)parse(start);if(end)parse(end);if(start&&end&&start>end)throw Error('The start date must be on or before the end date.');return {start_date:start||'',end_date:end||'',period:start||end?'range':'all'};}
  function calendar(year,unit,count=1,quarter=1){year=Number(year);count=Number(count);quarter=Number(quarter);if(!Number.isInteger(year)||year<1||year>9999||!Number.isInteger(count)||count<1||quarter<1||quarter>4)throw Error('Choose a valid year and positive window length.');const start=`${String(year).padStart(4,'0')}-${unit==='quarter'?String((quarter-1)*3+1).padStart(2,'0'):'01'}-01`;const end=addDays(shift(start,count*(unit==='quarter'?3:12)),-1);return range(start,end);}
  function rolling(count,unit,through=today()){count=Number(count);if(!Number.isInteger(count)||count<1)throw Error('Window length must be a positive whole number.');return range(addDays(shift(through,-count*(unit==='quarter'?3:12)),1),through);}
  function lastQuarter(through=today()){const d=parse(through),q=Math.floor(d.getUTCMonth()/3);return calendar(d.getUTCFullYear()-(q===0), 'quarter',1,q||4);}
  function bounds(value,precision){if(!value)return null;const year=value.slice(0,4);if(value.length===4||precision==='provider_day_unverified'||precision==='provider_date_unverified')return [year+'-01-01',year+'-12-31'];if(value.length===7)return [value+'-01',addDays(shift(value+'-01',1),-1)];return [value,value];}
  root.CairnPeriods={today,range,calendar,rolling,lastQuarter,bounds,shift,addDays};
})(typeof window==='undefined'?globalThis:window);
