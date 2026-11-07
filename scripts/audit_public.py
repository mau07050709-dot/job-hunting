"""Fail a public source audit on runtime state, personal paths or obvious secrets.

Heuristic aid, not proof that arbitrary future content is safe. No matched secret
value is printed. Keep private audit baselines outside this repository.
"""
import json,re,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PATTERNS={
 'personal_absolute_path':re.compile(r"(?i)[A-Z]:[/\\]+Users[/\\]+[^/\\\s]+"),
 'private_key':re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
 'live_service_token':re.compile(r"(?:ghp_|github_pat_|sk-proj-)[A-Za-z0-9_]{20,}"),
}
FORBIDDEN_DIRS={'data','backups','.venv','venv','__pycache__','.pytest_cache','dist','build','screenshots','traces'}
FORBIDDEN_EXT={'.sqlite','.sqlite3','.db','.log','.har','.pem','.pfx','.p12','.pyc','.pyo','.pdf','.doc','.docx','.xlsx','.mp4','.webm','.exe','.dll','.onnx'}
ALLOWED_BINARY={'job_hunting.ico'}

def audit(root=ROOT):
 findings=[];files=0
 for path in root.rglob('*'):
  rel=path.relative_to(root)
  if '.git' in rel.parts:continue
  if path.is_symlink():findings.append((rel.as_posix(),'symbolic_link'));continue
  if path.is_dir():
   if path.name in FORBIDDEN_DIRS or path.name.endswith('.egg-info'):findings.append((rel.as_posix(),'generated_or_private_directory'))
   continue
  if not path.is_file():continue
  files+=1
  if (path.name.startswith('.env') and path.name!='.env.example') or path.name=='config.json' or path.name in {'extension-pair.json','notice-video.json','section-backgrounds.json'} or path.suffix.lower() in FORBIDDEN_EXT:findings.append((rel.as_posix(),'private_or_generated_file'))
  if path.name in ALLOWED_BINARY:continue
  try:text=path.read_text(encoding='utf-8-sig')
  except UnicodeError:findings.append((rel.as_posix(),'unreviewed_binary'));continue
  for label,pattern in PATTERNS.items():
   if pattern.search(text):findings.append((rel.as_posix(),label))
 return {'files_scanned':files,'findings':[{'file':f,'reason':r} for f,r in findings]}

if __name__=='__main__':
 result=audit();print(json.dumps(result,indent=2));sys.exit(bool(result['findings']))
