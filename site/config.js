/*
 * Bird Models — configuration du site.
 * TRY_URL : destination de tous les boutons « Essayer Bird » / « Try Bird ».
 *   "/" : le chat Bird (le site est servi par l'application, sous /a-propos/).
 *   Remplacez par l'URL de l'application, par ex. "https://app.example.com".
 * CONTACT_EMAIL : adresse de contact. Vide (par défaut) : les liens « Nous écrire » mènent à la page
 *   « Entraîner Bird » (comment nous travaillons ensemble). Renseignée (par ex. "bonjour@votre-domaine.fr") :
 *   tous les liens « Nous écrire » et « Parler de votre projet » ouvrent un mail vers elle.
 */
window.BIRD_CONFIG = Object.freeze({
  TRY_URL: "/",
  CONTACT_EMAIL: ""
});
