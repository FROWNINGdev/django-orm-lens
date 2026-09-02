# Riferimento delle regole

Questa sezione contiene la traduzione italiana delle regole di Django ORM Lens relative alla definizione dei modelli. Ogni codice `DOL` identifica un controllo statico eseguito dall'estensione VS Code durante la scrittura del codice.

Per le regole non ancora tradotte, consulta il [riferimento completo in inglese](../../../rules/README.md).

## Regole di definizione dei modelli

| Codice | Regola | Categoria | Gravità predefinita | Applicabilità |
|---|---|---|---|---|
| [DOL011](DOL011.md) | `null=True` su CharField/TextField | model | warning | suggestion |
| [DOL012](DOL012.md) | Modello privo del metodo `__str__` | model | info | suggestion |
| [DOL013](DOL013.md) | ForeignKey senza `on_delete` | model | error | suggestion |
| [DOL014](DOL014.md) | CharField senza `max_length` | model | error | suggestion |
| [DOL015](DOL015.md) | `max_length` su TextField non ha effetto sul database | model | hint | suggestion |
