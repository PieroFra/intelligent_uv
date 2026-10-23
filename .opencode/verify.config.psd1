@{
    # Sorgente attivo: package single-file con operatori in operators\.
    Monolith      = '__init__.py'
    Sources       = @('operators')
    Runner        = '.opencode\scripts\run_tests.ps1'
    RunnerArgs    = @()
    # Il runner produce "RISULTATO passati=N falliti=M": il totale atteso
    # viene ricavato dal riepilogo, non dichiarato qui.
    ExpectedTotal = 0
    DiffPaths     = @('__init__.py', 'operators/')
    IndexOutput   = '.opencode\INDEX.md'
}
