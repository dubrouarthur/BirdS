/*
 * Bird Models — configuration du site.
 * TRY_URL : destination de tous les boutons « Essayer Bird » / « Try Bird ».
 *   "/" : le chat Bird (le site est servi par l'application, sous /a-propos/).
 *   Remplacez par l'URL de l'application, par ex. "https://app.example.com".
 * CONTACT_EMAIL : adresse de contact. Vide (par défaut) : la section Contact, le lien « Contact » des menus et
 *   les boutons « Nous écrire » / « Parler de votre projet » restent cachés (pas de lien qui promet d'écrire sans
 *   le permettre). Renseignée (par ex. "bonjour@votre-domaine.fr") : ils apparaissent et ouvrent un mail vers elle.
 */
window.BIRD_CONFIG = Object.freeze({
  TRY_URL: "/",
  CONTACT_EMAIL: ""
});
