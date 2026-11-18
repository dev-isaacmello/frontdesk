/** Desktop only: what the pane beside the list says while no conversation is open. */
export default function InboxPage() {
  return (
    <div className="hidden h-full flex-col items-center justify-center px-8 text-center lg:flex">
      <p className="text-lg font-medium">Escolha uma conversa</p>
      <p className="mt-1.5 max-w-sm text-ink-soft">
        Abra uma conversa da lista para ler as mensagens e ver como cada resposta foi feita.
      </p>
    </div>
  );
}
