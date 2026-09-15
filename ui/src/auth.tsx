import { createContext, useContext } from "react";
import { Me } from "./api";

export const AuthCtx = createContext<Me>({ auth_enabled: false, user: null });

export function useAuth(): Me {
  return useContext(AuthCtx);
}
