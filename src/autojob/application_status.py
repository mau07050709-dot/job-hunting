"""Mensajes de avance basados en acciones observadas, sin dar por enviado un formulario."""

def review_reason(row, fallback=''):
    evaluation=row.get('evaluation') or {};reasons=[]
    if row.get('excluded'):return 'La oferta está descartada por el usuario.'
    if evaluation.get('geography')!='CONFIRMADO':reasons.append('no está confirmado que la oferta permita trabajar desde Costa Rica')
    if evaluation.get('availability')!='ABIERTA':reasons.append('no se ha verificado que siga aceptando candidaturas')
    for assessment in evaluation.get('assessments',[]):
        if assessment.get('state') not in {'POR VERIFICAR','NO CUMPLE'}:continue
        evidence=' '.join(str(assessment.get('evidence') or '').split())
        if evidence:
            reasons.append(('falta comprobar el requisito: ' if assessment['state']=='POR VERIFICAR' else 'la evaluación detecta un requisito no cumplido: ')+evidence[:220])
        if len(reasons)>=4:break
    selection=evaluation.get('resume_selection') or {}
    if evaluation and not selection.get('resume_id'):reasons.append('falta seleccionar un CV adecuado')
    if not reasons:return fallback or 'La candidatura necesita revisión antes de continuar automáticamente.'
    return '; '.join(reasons)+'.'


def consultation_message(reason='',closed=False,http=None):
    if closed:return 'OFERTA CERRADA — SOLO CONSULTA\nLa página indica que esta vacante ya no está disponible. No se rellenaron datos ni se adjuntó el CV en esta consulta. Puedes saltarla; se conserva su historial.'
    if http:return 'ERROR DEL PORTAL — SOLO CONSULTA\nLa página respondió HTTP '+str(http)+'. No se rellenaron datos ni se adjuntó el CV en esta consulta. Puedes revisar el error en Brave o saltar esta oferta.'
    return ('SOLO CONSULTA — NO HAY UN FORMULARIO PREPARADO\n'
            'Se abrió el anuncio o enlace seleccionado en Brave. En esta consulta no se rellenaron datos, no se adjuntó el CV ni se envió una postulación.\n'
            'Motivo: '+reason+'\n'
            'Esta ventana permite revisar la oferta y mantiene bloqueados los envíos. No hay una etapa rellenada que puedas continuar aquí; puedes saltar la oferta o comprobar los requisitos en MIS DATOS.')


def prepared_message(state,attached,verified,preparation_only=False):
    pending=list(dict.fromkeys(e.get('group') or e.get('label') or 'Campo obligatorio' for e in state.get('pending',[])))
    obstacles=list(dict.fromkeys(b.get('type','Revisión') for b in state.get('document',{}).get('obstacles',[])+state.get('preview',{}).get('blocks',[])))
    missing_form=any(kind in {'SIN FORMULARIO','FORMULARIO NO IDENTIFICADO COMO POSTULACIÓN','VACANTE POR VERIFICAR'} for kind in obstacles)
    header='NO PUDE PREPARAR LA POSTULACIÓN' if missing_form else 'NECESITO TU AYUDA — FORMULARIO ABIERTO EN BRAVE' if pending or obstacles else 'FORMULARIO COMPROBADO — CONTINUANDO'
    progress=str(verified)+' campos con valores comprobados; '+('CV adjunto y comprobado.' if attached else 'CV todavía no adjunto o no comprobado.')
    missing='; '.join(pending[:5]+obstacles[:3]) or 'No quedan campos obligatorios desconocidos en esta etapa.'
    next_step='Completa lo pendiente directamente en esa misma ventana de Brave. Se comprobará la solución y se continuará con el permiso vigente.'
    if preparation_only:next_step='Completa lo pendiente en esa misma ventana de Brave. Esta recuperación solo prepara; pulsa INICIAR para autorizar la continuación automática del envío.'
    if missing_form:next_step='No hay un formulario preparado que continuar. Revisa la página abierta en Brave o salta esta oferta.'
    return header+'\n'+progress+'\nMe detuve en: '+missing+'\n'+next_step
