# runtime/

Foto e audio generati a runtime (`photos/`, `audio/`) finiscono qui. Quel
contenuto è ricreato a ogni esecuzione: puoi svuotarlo in sicurezza.

`stories_it.json` / `stories_en.json` / `stories_sl.json` sono invece **dati
permanenti**: il pool di storie pre-generate (copie di
`lettura storie/stories2*.json`, vedi `docs/05_modelli_e_storie.md`), allineate
per indice fra le tre lingue. Vanno copiati sul Raspberry Pi insieme al resto
di `Production/` e **non** vanno cancellati insieme a `photos/`/`audio/`.
