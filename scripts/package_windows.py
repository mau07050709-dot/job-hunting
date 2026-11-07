"""Build an audited source ZIP; no runtime state, installer or dependencies."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import tomllib
from audit_public import audit


def package(root):
    # Existing dist archives are not repository inputs and are checked separately.
    findings=[f for f in audit(root)['findings'] if not f['file'].startswith('dist/')]
    if findings:raise ValueError('Public source audit failed: '+', '.join(f['file'] for f in findings))
    snapshot=[p for p in root.rglob('*') if p.is_file() and not any(x in {'dist','.git'} for x in p.relative_to(root).parts)]
    banned={'data','backups','.venv','__pycache__','.pytest_cache','build'}
    if any(any(x in banned or x.endswith('.egg-info') for x in p.relative_to(root).parts) for p in snapshot):raise ValueError('Remove runtime/build data before packaging.')
    for p in snapshot:
        if p.name=='config.json' or p.suffix.lower() in {'.sqlite3','.db','.log','.exe','.dll','.pyc'}:raise ValueError('Private or generated file cannot be packaged.')
    version=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    output=root/'dist'/f'Job-Hunting-{version}-Source.zip';output.parent.mkdir(exist_ok=True)
    with ZipFile(output,'w',compression=ZIP_DEFLATED) as z:
        for p in sorted(snapshot):z.write(p,'Job-Hunting/'+p.relative_to(root).as_posix())
    return output

if __name__=='__main__':print(package(Path(__file__).resolve().parents[1]))
