"""Duraciones auditables: no asigna días ficticios a fechas parciales."""
from calendar import monthrange
from datetime import date,timedelta,datetime
from zoneinfo import ZoneInfo
import re

def bounds(value,today):
 if value and value.casefold() in {'present','current','actualidad','presente'}:return today,today,'current'
 if not value:return None
 value=value.strip()
 if re.fullmatch(r'\d{4}',value):
  year=int(value);return date(year,1,1),date(year,12,31),'year'
 if re.fullmatch(r'\d{4}-\d{2}',value):
  year,month=map(int,value.split('-'));return date(year,month,1),date(year,month,monthrange(year,month)[1]),'month'
 parsed=date.fromisoformat(value);return parsed,parsed,'day'

def union(intervals):
 result=[]
 for start,end in sorted(intervals):
  if start>=end:continue
  if result and start<=result[-1][1]:result[-1]=(result[-1][0],max(end,result[-1][1]))
  else:result.append((start,end))
 return result

def summarize(intervals):
 days=0;months=0;remaining=0
 for start,end in union(intervals):
  days+=(end-start).days
  count=(end.year-start.year)*12+end.month-start.month
  def advance(n):
   year=start.year+(start.month-1+n)//12;month=(start.month-1+n)%12+1
   return date(year,month,min(start.day,monthrange(year,month)[1]))
  if advance(count)>end:count-=1
  months+=count;remaining+=(end-advance(count)).days
 return {'days':days,'calendar_years':months//12,'calendar_months':months%12,'remaining_days':remaining}

def calculate_experience(records,category=None,today=None):
 today=today or datetime.now(ZoneInfo('America/Costa_Rica')).date();minimum=[];maximum=[];details=[];unknown=[]
 for record in records:
  if record.get('kind','employment')!='employment':continue
  text=' '.join(str(record.get(k) or '') for k in ('position','description')).casefold()
  terms={'customer_service':('customer','cliente','support','servicio'),'programming':('developer','programming','programador','desarrollador','software')}
  if category and not any(term in text for term in terms.get(category,(category,))):continue
  try:
   start=bounds(record.get('start_date'),today);end=bounds(record.get('end_date'),today)
   if not start or not end or start[0]>end[1] or start[0]>today:raise ValueError()
   low=(start[1],min(end[0],today)+timedelta(days=1));high=(start[0],min(end[1],today)+timedelta(days=1))
   minimum.append(low);maximum.append(high)
   details.append({'id':record.get('id'),'start':record.get('start_date'),'end':record.get('end_date'),'precision':[start[2],end[2]],'minimum':summarize([low]),'maximum':summarize([high])})
  except (ValueError,TypeError,OverflowError):unknown.append(record.get('id'))
 if not details:return {'status':'unknown','reason':'No hay períodos laborales suficientes para esa categoría.','unknown_records':unknown}
 return {'status':'unknown' if unknown else 'exact' if all(d['precision']==['day','day'] for d in details) else 'range','minimum':summarize(minimum),'maximum':summarize(maximum),'records':details,'unknown_records':unknown,'assumptions':'Fecha final inclusiva; unión de períodos superpuestos; fechas parciales producen límites, no días supuestos. Los registros sin fechas impiden afirmar un total.'}
