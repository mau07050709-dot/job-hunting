import secrets,string
from autojob.auth.vault import Secret

def generate(length=24,symbols=True,minimum=16,maximum=128,allowed_symbols='!@#$%&*+-_=?:'):
    if type(length) is not int or not 16<=minimum<=maximum<=128 or not minimum<=length<=maximum:
        raise ValueError('Longitud fuera de la política admitida (16 a 128).')
    if not isinstance(allowed_symbols,str) or any(c not in string.punctuation for c in allowed_symbols):raise ValueError('Conjunto de símbolos inválido.')
    groups=[string.ascii_uppercase,string.ascii_lowercase,string.digits]
    if symbols:
        if not allowed_symbols:raise ValueError('El portal no admite los símbolos configurados.')
        groups.append(allowed_symbols)
    alphabet=''.join(groups);chars=[secrets.choice(g) for g in groups]
    chars.extend(secrets.choice(alphabet) for _ in range(length-len(chars)))
    for i in range(len(chars)-1,0,-1):
        j=secrets.randbelow(i+1);chars[i],chars[j]=chars[j],chars[i]
    return Secret(''.join(chars))
