"""Resumable setup for an existing server; uses the same API as future clients."""
import getpass
import membrain_sdk as sdk
from pydantic import ValidationError
from ..types import ClientError
from . import models
from ..terminal import select


def run(backend, read=input, write=print, secret=getpass.getpass) -> bool:
    """Configure backend through injected read/write/secret prompts; return whether reachable."""
    try:
        report = backend.readiness()
    except ClientError as error:
        write(str(error))
        write('Start the API, database and worker, then run membrain setup again.')
        return False
    while True:
        title = (f'Setup — database ready: {report.database.ready}; worker running: {report.worker.ready}; '
                 f'chat configured: {report.settings.chat.configured}; embeddings configured: {report.settings.embeddings.configured}')
        choices = [('1', 'Keep settings and finish'), ('2', 'Configure chat model'),
                   ('3', 'Configure embeddings'), ('4', 'Set database connection'),
                   ('5', 'Validate configured capabilities'), ('6', 'Disable a model capability'),
                   ('7', 'Inspect or finish an embedding migration'), ('0', 'Finish later')]
        try:
            choice = select(title, choices, read, write, prompt='Setup choice: ').strip()
            if choice in ('0', '1', '/back', '/quit', '/menu'):
                if not report.database.ready:
                    write('Database connection/migrations still need attention. Apply migrations using the server setup command: python -m app.setup --migrate.')
                if not report.worker.ready:
                    write('Start the server worker for organization and learning tasks. Raw captures can still be saved when the database is ready.')
                return True
            if choice == '2':
                saved = backend.execute(backend.setup.save_setup, sdk.SetupConfiguration(chat=models.chat(read, secret, write)))
                if getattr(saved, 'environment_overrides', []):
                    write('Environment overrides saved values for: ' + ', '.join(saved.environment_overrides))
                write('Chat settings saved on the server.')
            elif choice == '3':
                endpoint = models.embeddings(read, secret, write)
                if report.settings.embeddings.configured:
                    migration = backend.execute(backend.setup.start_migration, sdk.MigrationRequest.from_dict(endpoint.to_dict()))
                    write(f'Embedding migration: {migration.id}; status {migration.status}. The current profile stays active until cutover. Use setup option 7 later.')
                else:
                    backend.execute(backend.setup.save_setup, sdk.SetupConfiguration(embeddings=endpoint))
                    write('Embedding settings saved on the server.')
            elif choice == '4':
                value = secret('PostgreSQL connection URL (blank: keep current): ')
                if value:
                    backend.execute(backend.setup.save_setup, sdk.SetupConfiguration(database_url=value))
                    write('Database settings saved on the server. Database switching and migrations use the server setup command.')
            elif choice == '5':
                capabilities = ['database']
                if report.settings.chat.configured:
                    capabilities.append('chat')
                if report.settings.embeddings.configured:
                    capabilities.append('embeddings')
                result = backend.execute(backend.setup.validate_setup, sdk.CapabilityCheck(capabilities=capabilities), _request_timeout=(2.0, 135.0))
                write(str({name: {'ready': probe.ready, 'detail': probe.detail} for name, probe in result.items()}))
            elif choice == '6':
                capability = read('Disable chat or embeddings? ').strip()
                if capability not in ('chat', 'embeddings'):
                    write('Choose chat or embeddings.')
                    continue
                backend.execute(backend.setup.save_setup, sdk.SetupConfiguration.from_dict({capability: None}))
                write('Capability disabled in server settings; environment overrides still take precedence.')
            elif choice == '7':
                from uuid import UUID
                identifier = UUID(read('Embedding migration UUID: ').strip())
                migration = backend.execute(backend.setup.get_migration, identifier)
                write(f'Status: {migration.status}; missing explanations: {migration.missing_explanations}')
                action = read('Action: status / cutover / cancel [status]: ').strip() or 'status'
                if action in ('cutover', 'cancel'):
                    migration = backend.execute(backend.setup.decide_migration, identifier, action)
                    write(f'Migration status: {migration.status}')
                elif action != 'status':
                    write('Unknown migration action.')
            else:
                write('Choose one of the displayed numbers.')
                continue
            report = backend.readiness()
            if report.settings.environment_overrides:
                write('Environment values override saved settings for: ' + ', '.join(report.settings.environment_overrides))
        except (EOFError, KeyboardInterrupt):
            write('\nSetup stopped. Completed changes are saved; unfinished input is discarded.')
            return True
        except models.Cancelled:
            write('Returned to setup. No model settings saved.')
        except ClientError as error:
            write(str(error))
        except (ValidationError, ValueError, TypeError):
            write('Invalid settings. Check the model name, profile, URL and numeric values. No secret values are displayed.')
