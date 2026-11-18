"use client";

import { useActionState } from "react";

import { signInAction, type SignInState } from "../actions";

const ERRORS: Record<NonNullable<SignInState["error"]>, string> = {
  missing: "Preencha o e-mail e a senha.",
  invalid: "E-mail ou senha incorretos.",
  unavailable: "Não foi possível entrar agora. Tente de novo em instantes.",
};

const FIELD =
  "mt-1.5 block h-12 w-full rounded-xl border border-line bg-surface px-3.5 outline-none placeholder:text-ink-soft focus:border-ink-soft";

export function SignInForm() {
  const [state, action, pending] = useActionState(signInAction, {});

  return (
    <form action={action} className="mt-8 flex flex-col gap-5">
      <label className="block text-sm font-medium">
        E-mail
        <input
          name="email"
          type="email"
          required
          maxLength={200}
          autoComplete="username"
          inputMode="email"
          autoCapitalize="none"
          defaultValue={state.email ?? ""}
          className={`${FIELD} text-base font-normal`}
        />
      </label>
      <label className="block text-sm font-medium">
        Senha
        <input
          name="password"
          type="password"
          required
          maxLength={200}
          autoComplete="current-password"
          className={`${FIELD} text-base font-normal`}
        />
      </label>
      {state.error ? (
        <p role="alert" className="text-sm text-danger">
          {ERRORS[state.error]}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={pending}
        className="h-12 rounded-full bg-accent font-medium text-accent-ink transition-opacity disabled:opacity-50"
      >
        {pending ? "Entrando" : "Entrar"}
      </button>
    </form>
  );
}
