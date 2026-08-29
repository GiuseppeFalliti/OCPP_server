import functools

routables = []


def on(action, *, skip_schema_validation=False):
    """
    Decoratore che registra una funzione come handler di una specifica Action.
    La funzione decorata puo' essere asincrona o sincrona.

    L'handler riceve argomenti con nome derivati dal payload della Action. Si
    raccomanda di usare `**kwargs` per ignorare eventuali argomenti aggiunti in
    futuro.

    L'handler deve restituire il payload appropriato da inviare al Charge Point.

    Esempio d'uso:

    ```
    class MyChargePoint(cp):
        @on(Action.boot_notification):
        async def on_boot_notification(
            self,
            charge_point_model,
            charge_point_vendor,
            **kwargs,
        ):
            print(f'{charge_point_model} from {charge_point_vendor} booted.')

            now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S') + "Z"
            return call_result.BootNotificationPayload(
                current_time=now,
                interval=30,
                status="Accepted",
            )
    ```

    Il decoratore accetta l'argomento opzionale `skip_schema_validation`, il cui
    valore predefinito e' False. Impostarlo a `True` disabilita la validazione
    dello schema per richiesta e risposta della route specifica.

    """

    def decorator(func):
        @functools.wraps(func)
        def inner(*args, **kwargs):
            return func(*args, **kwargs)

        inner._on_action = action
        inner._skip_schema_validation = skip_schema_validation
        if func.__name__ not in routables:
            routables.append(func.__name__)
        return inner

    return decorator


def after(action, inject_response=False):
    """Decoratore che registra una funzione come hook post-richiesta.

    Gli argomenti dell'hook sono i dati contenuti nel payload della Action.

    Esempio d'uso:

        @after(Action.boot_notification):
        def after_boot_notification():
            pass

    Quando ``inject_response`` e' ``True``, la risposta prodotta dal relativo
    handler ``@on`` e inviata alla controparte viene passata all'hook come
    argomento con nome ``call_response``. In questo modo non serve salvare la
    risposta in una variabile temporanea. Il valore predefinito e' ``False`` per
    mantenere la compatibilita' all'indietro:

        @after(Action.boot_notification, inject_response=True):
        def after_boot_notification(self, call_response, **kwargs):
            ...

    """

    def decorator(func):
        @functools.wraps(func)
        def inner(*args, **kwargs):
            return func(*args, **kwargs)

        inner._after_action = action
        inner._inject_response = inject_response
        if func.__name__ not in routables:
            routables.append(func.__name__)
        return inner

    return decorator


def create_route_map(obj):
    """
    Esamina tutti gli attributi della classe alla ricerca di quelli decorati con
    `@on()`. Restituisce un dizionario in cui i nomi delle Action sono le chiavi
    e le funzioni decorate sono i valori.

    Per esempio, si consideri la seguente classe:

        class ChargePoint:

            @on(Action.boot_notification)
            def on_boot_notification(self, *args, **kwargs):
                pass

            @after(Action.boot_notification)
            def after_boot_notification(self, *args, **kwargs):
                pass


    In questo caso restituisce:

        {
            Action.boot_notification: {
                '_on_action': <reference to 'on_boot_notification'>,
                '_after_action': <reference to 'after_boot_notification'>,
                '_skip_schema_validation': False,
            },
        }

    """
    routes = {}
    for attr_name in routables:
        for option in ["_on_action", "_after_action"]:
            try:
                attr = getattr(obj, attr_name)
                action = getattr(attr, option)

                if action not in routes:
                    routes[action] = {}

                # Le route decorate con `@on()` possono essere configurate per
                # saltare la validazione di input e output. Per maggiori informazioni,
                # consultare la docstring di `on()`.
                if option == "_on_action":
                    routes[action]["_skip_schema_validation"] = getattr(
                        attr, "_skip_schema_validation", False
                    )

                routes[action][option] = attr

            except AttributeError:
                continue

    return routes
