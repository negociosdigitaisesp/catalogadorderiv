-- Desabilitar RLS para permitir consulta pública (anon)
-- Já que o foco é um Dashboard de Inteligência Aberto

ALTER TABLE public.hft_oracle_results DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.hft_catalogo_estrategias DISABLE ROW LEVEL SECURITY;

-- Garantir permissões de SELECT para anon e authenticated
GRANT SELECT ON public.hft_oracle_results TO anon, authenticated;
GRANT SELECT ON public.hft_catalogo_estrategias TO anon, authenticated;

-- Garantir que anon/authenticated possam ver a tabela
GRANT USAGE ON SCHEMA public TO anon, authenticated;
