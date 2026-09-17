import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!url || !anonKey) {
  // On ne bloque pas le build/dev, mais on prévient tôt : sans ces deux
  // variables, aucun appel Supabase (donc aucune connexion) ne peut marcher.
  console.error(
    'VITE_SUPABASE_URL et/ou VITE_SUPABASE_ANON_KEY manquent. Voir frontend/README.md.',
  )
}

export const supabase = createClient(url ?? '', anonKey ?? '')
