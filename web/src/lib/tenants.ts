/**
 * The businesses the demo can talk to. They mirror the seed of the backend; the panel
 * will read them from the API once it has an owner login.
 */
export type Tenant = {
  slug: string;
  name: string;
  summary: string;
  suggestions: readonly string[];
};

export const TENANTS: readonly Tenant[] = [
  {
    slug: "navalha",
    name: "Barbearia Navalha",
    summary: "Corte e barba com hora marcada, de terça a sábado.",
    suggestions: [
      "Quanto custa o corte?",
      "Tem horário amanhã para corte e barba?",
      "Quero agendar corte amanhã às 10h com o Caio",
      "Preciso cancelar meu horário",
    ],
  },
  {
    slug: "ponto-final",
    name: "Arena Ponto Final",
    summary: "Quadras de society e de areia, todos os dias até as 23h.",
    suggestions: [
      "Qual o valor do society?",
      "Tem horário sábado para areia?",
      "Quero reservar society sábado às 19h",
      "Quais são meus agendamentos?",
    ],
  },
];

export function findTenant(slug: string): Tenant | undefined {
  return TENANTS.find((tenant) => tenant.slug === slug);
}
