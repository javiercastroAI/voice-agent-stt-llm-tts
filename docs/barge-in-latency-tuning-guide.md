# Playbook de barge-in y latencia

Este documento es una guía operativa para diagnosticar, ajustar y validar la
experiencia de interrupción y velocidad en un agente de voz. Está pensado para
uso continuo del equipo de ingeniería: cada cambio debe poder medirse,
repetirse y compararse.

## 1. Principios de trabajo

- No optimicéis por sensación. Usad la sensación para detectar problemas, pero
  decidid con telemetría.
- No mezcléis objetivos. Latencia y barge-in comparten audio, pero fallan por
  causas distintas.
- Cambiad una variable cada vez. Si se tocan silencio, VAD, prompt y TTS a la
  vez, no sabréis qué funcionó.
- Priorizad primero no cortar al usuario. Una respuesta 200 ms más rápida no
  compensa perder las últimas palabras de una objeción.
- Validación manual y métricas deben contar la misma historia. Si una métrica
  mejora pero la llamada suena peor, el cambio no está listo.
- La brevedad del agente debe venir del prompt y de la estrategia
  conversacional, no de truncar tokens hasta dejar frases incompletas.

## 2. Qué significa latencia

La latencia percibida es la suma de varios tramos:

1. El usuario termina de hablar.
2. VAD/STT detecta que hay silencio suficiente.
3. STT entrega transcripción final.
4. El runtime marca end-of-utterance.
5. El LLM empieza a generar.
6. TTS empieza a devolver audio.
7. El audio llega al usuario.

Medid cada tramo por separado:

- **Speech end to final transcript:** cuello de botella en STT o endpointing.
- **Final transcript to turn completed:** retraso al cerrar el turno.
- **EOU total:** tiempo observado desde final de habla hasta turno completado.
- **LLM TTFT:** tiempo hasta primer token del modelo.
- **TTS TTFB:** tiempo hasta primer audio del sintetizador.
- **TTS audio duration:** duración de la respuesta hablada.
- **VAD average inference duration:** coste del detector de voz.

Ejemplo práctico:

- Si el usuario termina de hablar y el agente tarda 2 segundos en arrancar, pero
  `llm_ttft_seconds` y `tts_ttfb_seconds` son bajos, mirad STT/EOU.
- Si el EOU es bajo y el agente sigue tardando, mirad LLM o TTS.
- Si el agente empieza rápido pero habla demasiado, la siguiente interacción
  parecerá lenta aunque el pipeline sea rápido.

## 3. Qué significa barge-in

Barge-in es la capacidad de que el usuario tome el turno mientras el agente
habla. El flujo correcto es:

1. El agente está hablando.
2. VAD detecta habla del usuario durante la voz del agente.
3. El runtime solicita interrupción inmediata del habla del agente.
4. STT confirma si había contenido real.
5. Si la interrupción es real, el agente responde a la última intención.
6. Si era ruido, respiración o una muletilla corta, el sistema ignora o reanuda.

No todo sonido debe cortar al agente. Separad tres casos:

- **Interrupción de mando:** "Espere", "pare", "no soy la persona", "eso no es
  correcto". Debe cortar rápido.
- **Backchannel:** "sí", "vale", "ajá", "mmm". Normalmente no debe redirigir el
  flujo salvo que el diseño conversacional lo espere.
- **Ruido:** golpe de mesa, respiración, eco, teclado, movimiento de micrófono.
  Debe descartarse.

## 4. Puntos del repositorio

- `voice_agent/config.py`: defaults y lectura de variables de entorno.
- `.env` y `.env.example`: configuración activa y configuración de referencia.
- `voice_agent/app.py`: arranque de sesión, eventos de métricas y telemetría.
- `voice_agent/barge_in.py`: política, estados, KPIs y escritura de eventos.
- `voice_agent/metrics.py`: métricas STT, EOU, LLM, TTS y VAD.
- `voice_agent/quality.py`: evaluación automática de calidad de telemetría.
- `voice_agent/web.py`: panel local de transcripción, métricas y barge-in.
- `scripts/evaluate-telemetry.py`: evaluación post-sesión desde SQLite.

Arranque local:

```bash
.venv/bin/python -m backend.app console
```

Al iniciar, abrid el `Transcript Web UI` que imprime la consola. El panel web
permite ver estado del usuario, estado del agente, métricas de latencia, KPIs de
barge-in y conversación sin depender solo del terminal.

## 5. Configuración base

Usad esta base para comparar cambios. Ajustad solo una variable por iteración:

```env
VOICE_PIPELINE_MODE=controlled_fast
OPENAI_MODEL=gpt-4o-mini
OPENAI_STT_LANGUAGE=es
OPENAI_MAX_COMPLETION_TOKENS=60
OPENAI_FAST_STT_MODEL=gpt-4o-mini-transcribe
OPENAI_FAST_STT_REALTIME=true
OPENAI_FAST_STT_TURN_SILENCE_MS=150
OPENAI_FAST_STT_PREFIX_PADDING_MS=300
OPENAI_FAST_STT_VAD_THRESHOLD=0.5
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=marin
OPENAI_TTS_RESPONSE_FORMAT=pcm
OPENAI_TTS_SPEED=1.05
BARGE_IN_ENABLED=true
BARGE_IN_TURN_DETECTION_MODE=auto
BARGE_IN_ENDPOINTING_MODE=dynamic
BARGE_IN_INTERRUPTION_MODE=vad
BARGE_IN_MIN_SPEECH_SECONDS=0.20
BARGE_IN_MIN_WORDS=2
BARGE_IN_FALSE_INTERRUPTION_TIMEOUT_SECONDS=1.2
BARGE_IN_RESUME_FALSE_INTERRUPTION=true
BARGE_IN_MIN_ENDPOINTING_DELAY_SECONDS=0.20
BARGE_IN_MAX_ENDPOINTING_DELAY_SECONDS=0.55
BARGE_IN_MIN_CONSECUTIVE_SPEECH_DELAY_SECONDS=0.10
BARGE_IN_CONFIRMATION_GRACE_SECONDS=6.0
BARGE_IN_IMMEDIATE_MUTE_ENABLED=true
BARGE_IN_TELEMETRY_PATH=logs/barge-in-telemetry.jsonl
BARGE_IN_SQLITE_PATH=logs/barge-in-telemetry.sqlite3
VOICE_METRICS_TELEMETRY_PATH=logs/voice-metrics-telemetry.jsonl
VOICE_METRICS_SQLITE_PATH=logs/voice-metrics-telemetry.sqlite3
```

`OPENAI_MAX_COMPLETION_TOKENS=60` evita que el agente corte frases antes de
terminarlas. Si queréis respuestas más cortas, ajustad prompt, modelo o estilo
de respuesta. No bajéis el cap hasta provocar frases incompletas.

## 6. Proceso de medición

1. Activad telemetría JSONL y SQLite.
2. Guardad la configuración base de `.env`.
3. Arrancad el agente.
4. Ejecutad siempre el mismo paquete de escenas.
5. Anotad observaciones humanas: cortes, esperas, frases perdidas, ruido,
   recuperación.
6. Detened la sesión.
7. Ejecutad evaluación:

```bash
.venv/bin/python scripts/evaluate-telemetry.py
```

8. Cambiad una variable.
9. Repetid exactamente las mismas escenas.
10. Comparad métricas y observaciones.
11. Conservad el cambio solo si mejora el objetivo y no degrada los guardrails.

### 6.1 Loop engineering manual

En la fase actual, una persona sigue haciendo de llamante. El sistema mide la
llamada, pero todavía no simula por sí mismo la voz humana a nivel de audio. El
flujo de trabajo es:

1. El tester humano ejecuta el paquete fijo de escenas.
2. Se termina la llamada.
3. Se registra la ejecución con telemetría, commit, configuración y veredicto
   manual.
4. El loop engineer revisa el informe y las notas humanas.
5. Se elige un único cambio de mayor impacto.
6. Se implementa y valida ese cambio.
7. El tester repite el mismo paquete de escenas.

El paquete versionado de escenas vive en:

```text
specs/scenarios/production-readiness.json
```

Después de terminar una llamada, registrad la ejecución:

```bash
python3 scripts/record-loop-run.py \
  --profile production \
  --manual-verdict unknown \
  --notes "Anotar cortes, pausas, recuperaciones incorrectas o backchannels problemáticos"
```

Si queréis evaluar solo los eventos nuevos desde una marca anterior, pasad los
ids guardados en el registro anterior:

```bash
python3 scripts/record-loop-run.py \
  --profile production \
  --voice-after-id 120 \
  --barge-after-id 45 \
  --manual-verdict pass \
  --notes "Sin cortes; interrupción B correcta; backchannel C no descarriló"
```

El registro queda en `logs/loop-runs/` e incluye:

- commit actual,
- estado del working tree,
- hash de `.env`,
- id y versión del paquete de escenas,
- rango de telemetría evaluado,
- informe automático,
- veredicto manual,
- estado `readyForProduction`.

No uséis `readyForProduction=true` como aprobación final aislada. La salida a
producción requiere al menos tres ejecuciones representativas consecutivas,
revisión humana y evidencia de validación.

Formato recomendado de registro:

```text
Fecha:
Commit/config:
Cambio probado:
Escenas ejecutadas:
Resultado esperado:
Resultado observado:
EOU promedio:
LLM TTFT promedio:
TTS TTFB promedio:
Immediate mute success:
False-candidate rate:
Decisión: mantener / revertir / repetir
```

## 7. Biblioteca de escenas manuales

Usad estas escenas como suite manual mínima. Repetidlas con la misma entonación
y distancia al micrófono cuando comparéis cambios.

### Escena A: turno normal

Usuario:

```text
Sí, soy la persona responsable. Dígame.
```

Esperado:

- El sistema no corta el final.
- El agente responde sin espera incómoda.
- EOU, LLM TTFT y TTS TTFB quedan dentro de rangos aceptables.

### Escena B: interrupción de mando

Mientras el agente habla, usuario:

```text
Espere, yo no soy la persona responsable.
```

Esperado:

- El agente deja de hablar rápido.
- La interrupción queda confirmada.
- La siguiente respuesta atiende esa intención, no continúa el guion anterior.

### Escena C: backchannel corto

Mientras el agente habla, usuario:

```text
Vale.
```

Esperado:

- No debe tratarse como objeción completa.
- Puede ignorarse, continuar o hacer una microadaptación, según diseño.
- No debe perder el hilo de la conversación.

### Escena D: falso positivo por ruido

Durante el habla del agente, moved ligeramente el micrófono o haced un sonido
breve no verbal.

Esperado:

- No debe generarse una respuesta nueva.
- Si se detecta candidato, debe expirar o clasificarse como falso.
- No debe aumentar el `false_candidate_rate` por encima del umbral aceptado.

### Escena E: objeción larga

Usuario:

```text
No reconozco esa mensualidad porque creo que ya la pagamos, y además necesito
que comprobéis si el cargo está duplicado.
```

Esperado:

- No se pierden las últimas palabras.
- El agente clasifica la objeción principal.
- El agente responde con un siguiente paso claro.

### Escena F: interrupción con enfado

Mientras el agente habla, usuario:

```text
No quiero seguir con esta llamada.
```

Esperado:

- El agente corta rápido.
- Da una razón útil y breve para continuar.
- Si el usuario rechaza dos veces, cierra sin insistir.

### Escena G: consulta o revisión

Usuario:

```text
Revíselo un momento, porque no me cuadra.
```

Esperado:

- El agente no se queda en silencio indefinidamente.
- Simula una revisión breve.
- Vuelve con un resultado, límite o siguiente paso concreto.

Ejemplo de respuesta aceptable:

```text
Lo reviso un momento... ya lo tengo. Aquí figura como pendiente; puedo registrar
la revisión por pago o duplicidad. ¿Cuál aplica?
```

## 8. Matriz de diagnóstico

| Síntoma | Métrica que confirma | Ajuste a probar primero | Riesgo |
| --- | --- | --- | --- |
| El agente tarda tras el final del usuario | EOU alto | Revisar `OPENAI_FAST_STT_TURN_SILENCE_MS` y delays de endpointing | Cortar finales de frase |
| El transcript final llega tarde | `speech_end_to_final_transcript` alto | Revisar STT realtime, idioma y VAD threshold | Fragmentar transcripciones |
| El turno se cierra tarde aunque STT ya terminó | `final_transcript_to_turn_completed` alto | Revisar integración de turn completion | Responder antes de contexto completo |
| El LLM tarda en empezar | `llm_ttft_seconds` alto | Reducir contexto, revisar modelo y temperatura | Respuestas menos ricas |
| El audio tarda en sonar | `tts_ttfb_seconds` alto | Revisar TTS, formato, streaming y longitud de texto | Voz menos natural |
| El agente habla demasiado | `tts_audio_duration` alto | Acortar prompt y estructura de respuesta | Sonar brusco |
| El usuario interrumpe y el agente no para | `immediate_mute_success_rate` bajo u overtalk alto | Revisar immediate mute y VAD | Falsos cortes |
| "Vale" corta el agente | `false_candidate_rate` o backchannels altos | Subir `BARGE_IN_MIN_WORDS` o `BARGE_IN_MIN_SPEECH_SECONDS` | Perder interrupciones cortas reales |
| Ruido dispara interrupciones | ignored turns altos | Subir VAD threshold o mínimos de habla | Menos sensibilidad |
| Se pierden finales de objeciones largas | fragmentación o quejas manuales | Subir silencio de STT o max endpointing delay | Más latencia |
| El agente no vuelve tras consultar | observación manual | Prompt y flujo de recuperación | Respuestas de relleno |

## 9. Recetas de ajuste

### Reducir latencia de cierre de turno

Probad en este orden:

1. Medid EOU antes.
2. Bajad ligeramente `OPENAI_FAST_STT_TURN_SILENCE_MS`.
3. Si funciona, repetid escenas E y G.
4. Si se pierden finales, deshaced o subid `BARGE_IN_MAX_ENDPOINTING_DELAY_SECONDS`.
5. Validación mínima: ninguna objeción larga queda cortada.

Ejemplo:

```env
OPENAI_FAST_STT_TURN_SILENCE_MS=180
```

Si con `150` corta finales y con `200` suena lento, probad valores intermedios
de forma controlada.

### Reducir falsos barge-ins

Probad en este orden:

1. Ejecutad escenas C y D.
2. Si hay falsos cortes, subid `BARGE_IN_MIN_WORDS` de `2` a `3`.
3. Si el ruido sigue cortando, subid `BARGE_IN_MIN_SPEECH_SECONDS` poco a poco.
4. Repetid escena B para asegurar que una interrupción real sigue cortando.

Ejemplo:

```env
BARGE_IN_MIN_WORDS=3
BARGE_IN_MIN_SPEECH_SECONDS=0.25
```

No apliquéis ambos cambios a la vez en la primera prueba.

### Mejorar interrupciones reales que llegan tarde

Probad en este orden:

1. Confirmad que `BARGE_IN_IMMEDIATE_MUTE_ENABLED=true`.
2. Revisad immediate mute success y overtalk.
3. Si el usuario empieza a hablar y el agente sigue, revisad VAD threshold.
4. Si el agente corta pero no responde a la intención, revisad confirmación STT
   y prompt de recuperación.

Ejemplo:

```env
BARGE_IN_CONFIRMATION_GRACE_SECONDS=6.0
```

La gracia permite que STT confirme una interrupción real aunque la detección VAD
haya vuelto antes a escucha.

### Reducir latencia LLM

Probad en este orden:

1. Medid `llm_ttft_seconds`.
2. Revisad tamaño del prompt y contexto acumulado.
3. Mantened respuestas con una pregunta concreta por turno.
4. Evitad pedir al modelo listas largas o razonamientos visibles.
5. No uséis un cap demasiado bajo para forzar brevedad.

Ejemplo de instrucción útil:

```text
Responde en una o dos frases cortas. Haz una sola pregunta concreta.
```

Ejemplo de instrucción problemática:

```text
Sé muy breve.
```

La segunda es ambigua y puede producir respuestas secas, incompletas o poco
accionables.

### Reducir latencia TTS

Probad en este orden:

1. Medid `tts_ttfb_seconds` y `tts_audio_duration`.
2. Si TTFB domina, revisad modelo, formato y posibilidad de streaming real.
3. Si audio duration domina, acortad el texto antes de tocar TTS.
4. Validación humana: la voz debe seguir sonando natural.

Ejemplo:

```env
OPENAI_TTS_RESPONSE_FORMAT=pcm
OPENAI_TTS_SPEED=1.05
```

No subáis velocidad hasta que la voz pierda claridad. En contact center, claridad
supera velocidad.

## 10. Ejemplos de prompt para recuperación

Tras una interrupción, el agente debe responder a la última intención del
usuario, no retomar mecánicamente el guion anterior.

Interrupción:

```text
Espere, no soy la persona responsable.
```

Respuesta adecuada:

```text
Entendido. ¿Me puede indicar quién gestiona estos pagos?
```

Respuesta deficiente:

```text
Como le decía, existe una incidencia administrativa...
```

Backchannel:

```text
Vale.
```

Respuesta adecuada si no cambia intención:

```text
Gracias. Le explico el punto concreto.
```

Objeción larga:

```text
Creo que ya está pagado y además puede estar duplicado.
```

Respuesta adecuada:

```text
Entiendo. Lo clasifico como posible pago ya realizado o duplicidad. ¿Cuál quiere
que revisemos primero?
```

Consulta:

```text
Compruébelo.
```

Respuesta adecuada:

```text
Lo reviso un momento... ya lo tengo. Figura pendiente aquí; puedo registrar la
revisión del pago. ¿Tiene justificante?
```

## 11. Umbrales iniciales de calidad

No los tratéis como SLAs finales. Son umbrales de laboratorio para detectar
regresiones:

- `turn_confirmation_rate`: objetivo inicial superior al 90%.
- `false_candidate_rate`: objetivo inicial inferior al 10%.
- `immediate_mute_success_rate`: objetivo inicial superior al 95%.
- `average_overtalk_seconds`: objetivo inicial inferior a 0.5 s.
- `llm_average_ttft_seconds`: objetivo inicial inferior a 1.5 s.
- `tts_average_ttfb_seconds`: objetivo inicial inferior a 1.5 s.
- `final_fragmented_transcripts`: objetivo inicial inferior al 10%.

Si no hay suficientes turnos o interrupciones, la evaluación debe quedar como
`insufficient_data`, no como éxito.

Para candidatos a producción, usad el perfil estricto:

```bash
python3 scripts/evaluate-telemetry.py --profile production --json
```

Objetivo de producción:

- `turn_confirmation_rate`: al menos 95%.
- `false_candidate_rate`: como máximo 5%.
- `immediate_mute_success_rate`: al menos 98%.
- `average_overtalk_seconds`: como máximo 0.25 s.
- `max_overtalk_seconds`: como máximo 1.0 s.
- `llm_average_ttft_seconds`: como máximo 0.9 s.
- `llm_max_ttft_seconds`: como máximo 2.0 s.
- `tts_average_ttfb_seconds`: como máximo 0.9 s.
- `tts_max_ttfb_seconds`: como máximo 2.0 s.
- `final_fragmented_transcripts`: como máximo 5%.

El perfil de laboratorio sigue siendo útil para exploración local:

```bash
python3 scripts/evaluate-telemetry.py --profile lab --json
```

## 12. Guardrails

- No bajéis silencios hasta que el agente pise al usuario.
- No subáis sensibilidad VAD hasta que el ruido corte llamadas.
- No ocultéis latencia con frases de relleno.
- No forcéis respuestas ultra cortas que suenen bruscas o incompletas.
- No cambiéis idioma STT en despliegues monolingües salvo prueba controlada.
- No optimicéis solo con un hablante, un micrófono y una habitación silenciosa.
- No deis por buena una mejora que solo funciona sin ruido.

## 13. Checklist antes de aceptar un cambio

- Hay telemetría antes y después con las mismas escenas.
- Se ha cambiado una sola variable o una sola pieza funcional.
- Mejora la métrica objetivo.
- No empeora finales de frase.
- No aumenta falsos barge-ins.
- No rompe backchannels.
- No empeora claridad ni naturalidad.
- El agente vuelve tras interrupciones y consultas.
- Las pruebas automáticas pasan.
- El cambio queda documentado con razón y resultado.

Validación mínima:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python scripts/validate-specs.py
./scripts/check-scaffold.sh
```

Si cambia cualquier contrato o interfaz compartida:

```bash
.venv/bin/python scripts/generate-contract-artifacts.py --check
```

## 14. Qué debe existir antes de producción

- Suite manual versionada de escenas.
- Dataset de voces con acentos, velocidades, ruido y pausas.
- Telemetría persistida por sesión.
- Evaluación automática post-sesión.
- Umbrales de regresión para barge-in, overtalk, TTFT, TTFB y fragmentación.
- Dashboard o alertas para degradaciones.
- Criterio explícito para distinguir backchannel, ruido e interrupción real.
- Prompt revisado para respuestas breves, completas y recuperables.
- Plan de rollback de configuración.

La solución correcta no es una variable mágica. Es una combinación disciplinada
de endpointing, VAD, STT, LLM, TTS, prompt, telemetría y pruebas repetibles.
