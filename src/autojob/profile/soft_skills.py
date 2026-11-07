"""Sugiere habilidades únicamente cuando una expresión figura en el CV."""
import re
import unicodedata

EXPRESSIONS = ['comunicación','communication','trabajo en equipo','teamwork','organización','organization','adaptabilidad','adaptability','resolución de problemas','problem-solving','problem solving','toma de decisiones','decision-making','decision making','resolución de conflictos','conflict resolution','aprendizaje rápido','fast learning','quick learner','atención al cliente','customer service','customer support','gestión del tiempo','time management','atención al detalle','attention to detail','pensamiento analítico','analytical thinking','coordinación','coordination','escucha activa','active listening','cross-team coordination','aprendizaje continuo','continuous learning']
def normalize(text):return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))
def extract_soft_skills(units):
 text=' '.join(unit.get('text','') for unit in units);normalized=normalize(text);result=[];seen=set()
 for phrase in EXPRESSIONS:
  match=re.search(r'(?<!\w)'+re.escape(normalize(phrase))+r'(?!\w)',normalized)
  if match:
   value=text[match.start():match.end()];key=normalize(value)
   if key not in seen:seen.add(key);result.append(value)
 return result
