# Google Drive da empresa (pasta `WhatsApp`)

Estado: o rclone (`~/.local/bin/rclone`, remote `drive-empresa`) copia `data/arquivos` para `WhatsApp/` no Drive a cada hora
(crontab → `ops/drive_sync.sh`). Só copia, nunca apaga no Drive. Inclui `Empresa/_Restrito`: o Drive deve ser acessível só
aos sócios. Os arquivos de trava/estado e o `_inbox` não sobem.

## Trocar para um client OAuth próprio (o client padrão do rclone será aposentado em 2026)

1. Abra https://console.cloud.google.com com a **conta da empresa** → seletor de projeto → **Novo projeto** → nome `sie-joy-bot`.
2. **APIs e serviços → Biblioteca** → procure **Google Drive API** → **Ativar**.
3. **APIs e serviços → Tela de consentimento OAuth** (ou "Google Auth Platform"):
   - Tipo de usuário: **Interno**, se a conta for Google Workspace; senão **Externo**.
   - Nome do app: `SIÉ JOY Arquivos`; e-mail de suporte e de contato: o seu.
   - Escopos: pode deixar vazio (o rclone pede `drive`).
   - Se **Externo**: em **Público-alvo** clique **Publicar app** (status "Em produção"). Em "Teste" o token expira em 7 dias.
     Na tela de aviso "app não verificado" ao autorizar: **Avançado → Acessar SIÉ JOY Arquivos**.
4. **Credenciais → Criar credenciais → ID do cliente OAuth** → tipo **App para computador (Desktop)** → nome `rclone`.
   Copie o **ID do cliente** e a **chave secreta**.
5. No WSL, com o túnel SSH aberto no seu computador (`ssh -p 2222 -L 53682:127.0.0.1:53682 paulojr@mpbflndsk201-wsl`):

   ```bash
   ./ops/drive_client.sh <ID_DO_CLIENTE> <CHAVE_SECRETA>
   ```

   O script grava as credenciais no remote e imprime um link de autorização: abra no navegador (com o túnel) e aceite.
6. Teste: `~/.local/bin/rclone lsd drive-empresa:` e `./ops/drive_sync.sh --dry-run`.

O mesmo client serve para a skill `google-workspace` do Hermes (Drive/Docs/Sheets pelo agente), se um dia quisermos
que o bot leia/escreva arquivos do Drive sob comando.
