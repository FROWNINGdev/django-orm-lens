# Riferimento delle regole

Questa sezione contiene la traduzione italiana delle regole di Django ORM Lens relative ai queryset e alla definizione dei modelli. Ogni codice `DOL` identifica un controllo statico eseguito dall'estensione VS Code durante la scrittura del codice.

Per le regole non ancora tradotte, consulta il [riferimento completo in inglese](../../../rules/README.md).

## Regole sui queryset

| Codice | Regola | Categoria | Gravità predefinita | Applicabilità |
|---|---|---|---|---|
| [DOL001](DOL001.md) | Preferire `.exists()` a `.count() > 0` | queryset | info | safe |
| [DOL002](DOL002.md) | Preferire `not .exists()` a `.count() == 0` | queryset | info | safe |
| [DOL003](DOL003.md) | Preferire `not .exists()` a `.first() is None` | queryset | info | safe |
| [DOL004](DOL004.md) | Preferire `.exists()` a `.first() is not None` | queryset | info | safe |
| [DOL005](DOL005.md) | Considerare `Q(...)` al posto della catena `.filter().exclude()` | queryset | hint | suggestion |
| [DOL006](DOL006.md) | Eliminare `list()` attorno a un QuerySet in un ciclo `for` | queryset | info | safe |
| [DOL007](DOL007.md) | Possibile N+1: accesso a un attributo dentro un ciclo `for` | queryset | warning | unsafe |
| [DOL008](DOL008.md) | Il nome del campo in un lookup sembra contenere un refuso | correctness | warning | suggestion |

## Regole di definizione dei modelli

| Codice | Regola | Categoria | Gravità predefinita | Applicabilità |
|---|---|---|---|---|
| [DOL011](DOL011.md) | `null=True` su CharField/TextField | model | warning | suggestion |
| [DOL012](DOL012.md) | Modello privo del metodo `__str__` | model | info | suggestion |
| [DOL013](DOL013.md) | ForeignKey senza `on_delete` | model | error | suggestion |
| [DOL014](DOL014.md) | CharField senza `max_length` | model | error | suggestion |
| [DOL015](DOL015.md) | `max_length` su TextField non ha effetto sul database | model | hint | suggestion |
