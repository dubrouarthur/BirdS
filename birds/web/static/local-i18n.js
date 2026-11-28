// Strings of « Bird local » (local.js), French first with English parity (tests/js/local.test.mjs).
// Kept apart from i18n.js and merged into its STRINGS at load, under the local.* prefix.

export const LOCAL_CMDS = {
  vllm: "vllm serve adubrou/Bird-S-4B --host 127.0.0.1 --port 8000",
  bird: "python scripts/bird_local.py",
};

export const LOCAL_STRINGS = {
  fr: {
    "local.name": "Bird local",
    "local.mode": "Bird local (votre machine)",
    "local.mode.hint":
      "Le modèle tourne chez vous avec vLLM. Vos conversations vont de ce navigateur à votre machine, sans passer par nos serveurs.",
    "local.connect": "Se connecter au Bird local",
    "local.searching": "Recherche de Bird local sur votre machine…",
    "local.found": "Bird local est prêt sur {host}.",
    "local.code": "Code d'appairage",
    "local.code.hint": "Affiché dans le terminal par la commande Bird local, par exemple ABCD-EFGH.",
    "local.remember": "Se souvenir de ce code sur cet appareil",
    "local.privacy":
      "Le code reste dans ce navigateur. Bird local n'accepte que ce site, sur votre machine, et seulement avec ce code.",
    "local.perm":
      "Votre navigateur peut demander l'accès aux appareils de votre réseau local : autorisez-le pour ce site.",
    "local.connecting": "Connexion…",
    "local.connected": "Connecté à Bird local",
    "local.connected.p": "Vos messages vont directement à votre machine ({host}). Modèle : {model}.",
    "local.connected.wait": "Vos messages vont directement à votre machine ({host}).",
    "local.disconnect": "Revenir au modèle hébergé",
    "local.forget": "Oublier le code",
    "local.toast.paired": "Connecté à Bird local.",
    "local.toast.off": "Retour au modèle hébergé.",
    "local.toast.forgot": "Code d'appairage oublié.",
    "local.err.shape": "Le code compte 8 caractères, par exemple ABCD-EFGH.",
    "local.err.invalid": "Ce code ne correspond pas. Recopiez celui affiché dans le terminal de Bird local.",
    "local.err.locked": "Trop d'essais : patientez une minute, puis réessayez.",
    "local.err.gone": "Bird local ne répond plus. Vérifiez qu'il tourne toujours, puis réessayez.",
    "local.err.pair":
      "Bird local demande le code d'appairage : il a peut-être redémarré avec un nouveau code. Reconnectez-vous dans les réglages.",
    "local.notbird": "Un autre programme répond sur le port {port} : ce n'est pas Bird local.",
    "local.down.title": "Bird local ne répond pas",
    "local.down.p": "Démarrez-le sur votre machine en trois étapes, puis réessayez.",
    "local.step1": "Lancez le serveur du modèle",
    "local.step2": "Lancez Bird local, dans le dossier de Bird",
    "local.step3": "Saisissez le code d'appairage qu'il affiche, dans Réglages → Modèle",
    "local.copy": "Copier la commande",
    "local.copied": "Commande copiée.",
    "local.retry": "Réessayer",
    "local.docs": "Le guide complet est dans docs/LOCAL.md.",
    "local.here": "Cette page est servie par Bird local, sur votre machine : tout reste chez vous.",
    "local.pair.title": "Appairer ce navigateur",
    "local.pair.p": "Entrez le code d'appairage affiché dans le terminal de Bird local.",
    "local.pair.go": "Appairer",
    "local.fp.measured":
      "Bird local : l'énergie de ces réponses est mesurée sur votre machine, par l'échantillonnage de votre carte graphique (nvidia-smi).",
    "local.fp.estimated":
      "Bird local : l'énergie de ces réponses est estimée pour votre machine à partir des tokens, avec les repères publiés d'un serveur vLLM. Lancez Bird local avec --measure-gpu pour la mesurer.",
  },
  en: {
    "local.name": "Bird local",
    "local.mode": "Bird local (your machine)",
    "local.mode.hint":
      "The model runs on your machine with vLLM. Your conversations go from this browser to your machine, never through our servers.",
    "local.connect": "Connect to Bird local",
    "local.searching": "Looking for Bird local on your machine…",
    "local.found": "Bird local is ready on {host}.",
    "local.code": "Pairing code",
    "local.code.hint": "Shown in the terminal by the Bird local command, for example ABCD-EFGH.",
    "local.remember": "Remember this code on this device",
    "local.privacy":
      "The code stays in this browser. Bird local accepts this site only, on your machine, and only with this code.",
    "local.perm": "Your browser may ask to access devices on your local network: allow it for this site.",
    "local.connecting": "Connecting…",
    "local.connected": "Connected to Bird local",
    "local.connected.p": "Your messages go straight to your machine ({host}). Model: {model}.",
    "local.connected.wait": "Your messages go straight to your machine ({host}).",
    "local.disconnect": "Back to the hosted model",
    "local.forget": "Forget the code",
    "local.toast.paired": "Connected to Bird local.",
    "local.toast.off": "Back to the hosted model.",
    "local.toast.forgot": "Pairing code forgotten.",
    "local.err.shape": "The code has 8 characters, for example ABCD-EFGH.",
    "local.err.invalid": "This code does not match. Copy the one shown in the Bird local terminal.",
    "local.err.locked": "Too many tries: wait a minute, then try again.",
    "local.err.gone": "Bird local stopped answering. Check that it is still running, then try again.",
    "local.err.pair":
      "Bird local asks for the pairing code: it may have restarted with a new code. Connect again in the settings.",
    "local.notbird": "Another program answers on port {port}: it is not Bird local.",
    "local.down.title": "Bird local is not answering",
    "local.down.p": "Start it on your machine in three steps, then try again.",
    "local.step1": "Start the model server",
    "local.step2": "Start Bird local, in the Bird folder",
    "local.step3": "Type the pairing code it shows, in Settings → Model",
    "local.copy": "Copy the command",
    "local.copied": "Command copied.",
    "local.retry": "Try again",
    "local.docs": "The full guide is in docs/LOCAL.md.",
    "local.here": "This page is served by Bird local, on your machine: everything stays with you.",
    "local.pair.title": "Pair this browser",
    "local.pair.p": "Enter the pairing code shown in the Bird local terminal.",
    "local.pair.go": "Pair",
    "local.fp.measured":
      "Bird local: the energy of these answers is measured on your machine, by sampling your graphics card (nvidia-smi).",
    "local.fp.estimated":
      "Bird local: the energy of these answers is estimated for your machine from the tokens, with the published figures of a vLLM server. Start Bird local with --measure-gpu to measure it.",
  },
};
