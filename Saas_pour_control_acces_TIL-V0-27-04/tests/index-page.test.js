'use strict';

// Tests de bout en bout de app/index.html dans Chromium (Playwright), contre le
// serveur local du projet sur un port libre. Plan « Logiciel TIL » : E0 a E14,
// plan « APERIO + biometrie » : E15 a E23, revue APERIO : E24 a E27.
// Aucune impression reelle (window.print neutralise), aucun export Excel.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { chargerGenerator } = require('./helpers/charger-generator');
const fx = require('./helpers/fixtures');
const { demarrerApp, preparerPage, chargerTillys, capturerPopup, largeurImage } = require('./helpers/page');

const TIL = chargerGenerator();
const OPTIONS = { timeout: 30000 };
const LOGO = 'img[src*="logo-fauche-digital.png"]';

let app;
before(async () => { app = await demarrerApp(); });
after(async () => { if (app) await app.fermer(); });

// Ouvre un contexte neuf avec la fixture, execute le scenario, ferme toujours.
async function avecPage(tillys, scenario) {
  const session = await preparerPage(app, tillys);
  try {
    return await scenario(session);
  } finally {
    await session.context.close();
  }
}

test('E0 (non-regression) aucune erreur de page au chargement et a l\'injection de la fixture', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page, erreurs }) => {
    await page.waitForTimeout(300);
    assert.deepEqual(erreurs.map(e => e.message), []);
  });
});

test('E1 en-tetes du tableau d\'adresses : vocabulaire terrain', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const entetes = await page.$$eval('#addr-table thead th', ths => ths.map(th => th.textContent.trim()));
    const attendus = ['Relais', 'LED Verte', 'LED Rouge', 'Buzzer', 'BP', 'Etat Porte', 'DM', 'AP Boite CA'];
    const positions = attendus.map(libelle => entetes.indexOf(libelle));
    positions.forEach((pos, i) => assert.ok(pos >= 0, `en-tete « ${attendus[i]} » absent : ${entetes.join(' | ')}`));
    assert.deepEqual(positions, [...positions].sort((a, b) => a - b), `ordre des en-tetes : ${entetes.join(' | ')}`);
    ['Lock', 'LED+', 'LED-', 'Capteur'].forEach(ancien => {
      assert.ok(!entetes.includes(ancien), `ancien en-tete « ${ancien} » encore present`);
    });
  });
});

test('E2 tableau d\'adresses rendu : equipements poses, ligne du lecteur de sortie, serrures', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const lignes = await page.evaluate(() => {
      renderTableauAdresses();
      return [...document.querySelectorAll('#addr-tbody tr')]
        .map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.replace(/\s+/g, ' ').trim()));
    });
    assert.equal(lignes.length, 25, '24 portes + 1 ligne de lecteur de sortie');

    const indexPorte = num => lignes.findIndex(cellules => cellules[0] === String(num).padStart(2, '0'));
    const porte1 = lignes[indexPorte(1)];
    assert.equal(porte1[12], 'DA0101', 'porte 1 : BP');
    assert.equal(porte1[14], 'DA0103', 'porte 1 : DM');
    assert.equal(porte1[15], '—', 'porte 1 : pas d\'AP');

    const porte3 = lignes[indexPorte(3)];
    assert.equal(porte3[12], '—', 'porte 3 : pas de BP');
    assert.equal(porte3[16], 'M2', 'porte 3 : commande hyperviseur');
    assert.equal(porte3[17], 'TN2', 'porte 3 : timer');

    const i2 = indexPorte(2);
    const sortie = (lignes[i2 + 1] || []).join(' | ');
    ['LA4', 'Lecteur de sortie', 'XA0306', 'XA0307', 'XA0308'].forEach(valeur => {
      assert.ok(sortie.includes(valeur), `ligne suivant la porte 2 sans « ${valeur} » : ${sortie}`);
    });

    assert.equal(lignes[i2][7], '🔒 KEL', 'serrure porte 2');
    assert.equal(porte3[7], '🔒 GÂCHE', 'serrure porte 3');
  });
});

test('E3 labelSerrure : libelles des verrouillages', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const libelles = await page.evaluate(() => ({
      kel: labelSerrure('KEL'),
      gacheMaj: labelSerrure('GACHE'),
      gacheMin: labelSerrure('gache'),
      aperio: labelSerrure('APERIO'),
      cmd: labelSerrure('CMD'),
      vide: labelSerrure(''),
      indefini: labelSerrure(undefined),
      ventouse: labelSerrure('VENTOUSE'),
    }));
    assert.deepEqual(libelles, {
      kel: '🔒 KEL',
      gacheMaj: '🔒 GÂCHE',
      gacheMin: '🔒 GÂCHE',
      aperio: 'APERIO',
      cmd: 'CMD',
      vide: '—',
      indefini: '—',
      ventouse: '🧲 VENTOUSE',
    });
  });
});

test('E4 export CSV : en-tete, ligne de sortie, BP/DM/AP vides, voies MLR8 et MLIO', OPTIONS, async () => {
  await avecPage(fx.fixtureModulesTerrain(TIL), async ({ page }) => {
    const csv = await page.evaluate(() => {
      window.__csv = null;
      window.telechargerContenu = contenu => { window.__csv = contenu; };
      exporterCSV();
      return window.__csv;
    });
    assert.equal(typeof csv, 'string', 'exporterCSV doit produire un contenu');
    const lignes = csv.split(/\r?\n/).filter(Boolean).map(l => l.split(';'));
    assert.equal(lignes[0].join(';'),
      'TriNum;PorteApp;ID;Bus;Carte;Lecteur;Description;Mode;Serrure;Relais;LED Verte;LED Rouge;Buzzer;BP;Etat Porte;DM;AP Boite CA;CmdHyper;Timer;Effraction;POTL');

    const i2 = lignes.findIndex(c => c[1] === '2');
    const sortie = lignes[i2 + 1] || [];
    assert.equal(sortie[5], 'LA4', 'lecteur de sortie de la porte 2');
    assert.equal(sortie[6], '"Hall - sortie"');
    assert.deepEqual(sortie.slice(10, 13), ['XA0306', 'XA0307', 'XA0308']);

    const porte3 = lignes.find(c => c[1] === '3');
    assert.deepEqual([porte3[13], porte3[15], porte3[16]], ['', '', ''], 'porte 3 : BP, DM, AP vides');

    const mlr8 = lignes.find(c => c[0] === 'MLR8 A9 R1');
    assert.ok(mlr8, 'voie R1 du MLR8 A9 absente du CSV');
    assert.equal(mlr8[9], 'XA0901', 'registre MLR8 en colonne Relais');
    const mlio = lignes.find(c => c[0] === 'MLIO A10 I1');
    assert.ok(mlio, 'voie I1 du MLIO A10 absente du CSV');
    assert.equal(mlio[lignes[0].indexOf('BP')], 'DA1001', 'registre MLIO en colonne BP');
  });
});

test('E5 etiquettes chantier des lecteurs dans le synoptique', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const resultat = await page.evaluate(() => {
      const t = APP.tillys[0];
      const ma1 = t.synopticModules.find(m => m.id === 'MA1');
      const ma3 = t.synopticModules.find(m => m.id === 'MA3');
      const meta = html => {
        const tpl = document.createElement('template');
        tpl.innerHTML = html;
        const el = tpl.content.querySelector('.synoptic-door-meta');
        return { texte: el.textContent.trim(), title: el.getAttribute('title') };
      };
      return {
        avecNumero: getPorteReaderChantierLabels({ lecteurEntree: 'LB', numeroEntree: '001' }, ['LA1']),
        sansNumero: getPorteReaderChantierLabels({ lecteurEntree: 'LB' }, ['LA1']),
        tropDeTetes: getPorteReaderChantierLabels({ lecteurEntree: 'LB', numeroEntree: '001' }, ['LA1', 'LA2']),
        porte1: meta(renderSynopticDoorNode(t, 0, ma1, 1)),
        porte3: meta(renderSynopticDoorNode(t, 0, ma1, 3)),
        porte2: meta(renderSynopticDoorNode(t, 0, ma3, 2)),
      };
    });
    assert.deepEqual(resultat.avecNumero, ['LB001']);
    assert.deepEqual(resultat.sansNumero, ['LA1']);
    assert.deepEqual(resultat.tropDeTetes, ['LA1', 'LA2']);
    assert.equal(resultat.porte1.texte, 'LB001');
    assert.equal(resultat.porte1.title, 'LA1');
    assert.equal(resultat.porte3.texte, 'LA2');
    assert.equal(resultat.porte2.texte, 'LA3 · LA4');
  });
});

test('E6 carnet de cables : avec boite de jonction, CMD/BP/DM partent de la BJ', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    // Lecture seule des lignes calculees : aucun export Excel declenche.
    const lignes = await page.evaluate(() => buildCarnetCableRows()
      .map(r => ({ code: r.codeDepart, depart: r.depart, equipement: r.equipementDepart })));
    const ligne = code => lignes.find(l => l.code === code);

    ['CMD A_N0_1', 'BP A_N0_1', 'DM A_N0_1'].forEach(code => {
      assert.ok(ligne(code), `ligne ${code} absente`);
      assert.equal(ligne(code).depart, 'BJ A_N0_1', `${code} doit partir de la boite de jonction`);
    });

    const bj = ligne('BJ A_N0_1');
    assert.ok(bj, 'ligne BJ A_N0_1 absente');
    assert.match(bj.depart, /Tillys 1/, 'la boite de jonction part du coffret / Tillys');

    const lecteur = ligne('001');
    assert.ok(lecteur, 'ligne du lecteur d\'entree de la porte 1 absente');
    assert.match(lecteur.depart, /Tillys 1/, 'le lecteur d\'entree part du coffret / Tillys');

    const cmd3 = ligne('CMD A_N0_3');
    assert.ok(cmd3, 'ligne CMD A_N0_3 absente');
    assert.match(cmd3.depart, /Tillys 1/, 'porte 3 sans BJ : CMD part du coffret / Tillys');
    assert.ok(!cmd3.depart.startsWith('BJ'), 'porte 3 sans BJ : CMD ne part pas d\'une BJ');
  });
});

test('E7 bandeau des coffrets : plus de compteur d\'elements lies', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const { lies, texte } = await page.evaluate(() => {
      const coffret = getProjectCoffrets()[0];
      const tpl = document.createElement('template');
      tpl.innerHTML = renderCoffretSummaryBar();
      return {
        lies: coffret ? getLinkedCoffretItems(coffret).length : 0,
        texte: tpl.content.textContent.replace(/\s+/g, ' ').trim(),
      };
    });
    assert.ok(lies >= 1, 'precondition : le coffret de la fixture doit avoir un element lie');
    assert.match(texte, /coffret/i);
    // Singulier ou pluriel : « 1 element lie » comme « 2 elements lies ».
    assert.doesNotMatch(texte, /li[ée]s?(?![a-z])/i, `bandeau : ${texte}`);
  });
});

test('E8 plan d\'implantation : A4 paysage, une page par coffret equipe, logo charge', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    const equipes = await page.evaluate(() => getProjectCoffrets()
      .filter(c => Array.isArray(c.configEquipements) && c.configEquipements.length > 0).length);
    assert.ok(equipes >= 1, 'precondition : au moins un coffret avec configEquipements');

    const popup = await capturerPopup(context, page, () => genererPlanImplantationComplet());
    const html = await popup.content();
    assert.match(html, /@page\s*\{\s*size:\s*A4 landscape/);
    assert.ok(!html.includes('A4 portrait'), 'aucune regle A4 portrait');
    assert.equal(await popup.locator('.coffret-print-page').count(), equipes);
    assert.ok(await largeurImage(popup, LOGO) > 0, 'logo Fauche non charge');
  });
});

test('E9 impression du synoptique coffret : A4 paysage et logo charge', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    await page.evaluate(() => ouvrirCoffretSynoptique(0));
    const svg = await page.locator('#coffret-synoptique-body svg').count();
    assert.ok(svg > 0, 'precondition : le synoptique coffret doit contenir un schema');

    const popup = await capturerPopup(context, page, () => imprimerCoffretSynoptique());
    // La fenetre lance l'impression au chargement : l'appel doit avoir ete intercepte.
    await popup.waitForFunction(() => window.__printAppels >= 1, null, { timeout: 5000 });
    const html = await popup.content();
    assert.match(html, /@page\s*\{\s*size:\s*A4 landscape/);
    assert.ok(!html.includes('A4 portrait'), 'aucune regle A4 portrait');
    assert.ok(await largeurImage(popup, LOGO) > 0, 'logo Fauche non charge');
  });
});

test('E10a bouton « Export PDF » de la liste des portes', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const bouton = page.locator('button[onclick="exporterListePortesPdf()"]');
    assert.equal(await bouton.count(), 1, 'bouton exporterListePortesPdf() absent');
    assert.equal((await bouton.textContent()).trim(), 'Export PDF');
  });
});

test('E10b PDF de reperage, 24 portes : sections, suites, cartouche en bas, pagination', OPTIONS, async () => {
  await avecPage(fx.fixture24Portes(TIL), async ({ context, page }) => {
    const popup = await capturerPopup(context, page, () => exporterListePortesPdf());
    await popup.waitForFunction(() => document.querySelectorAll('.rep-page').length > 0);
    const mesure = await popup.evaluate(() => [...document.querySelectorAll('.rep-page')].map(pageEl => {
      const body = pageEl.querySelector('.rep-body');
      const cartouche = pageEl.querySelector('.rep-cartouche');
      const rectPage = pageEl.getBoundingClientRect();
      const bordBas = parseFloat(getComputedStyle(pageEl).borderBottomWidth) || 0;
      const blocs = [];
      [...body.children].forEach(el => {
        if (el.classList.contains('rep-section-titre')) blocs.push({ titre: el.textContent.trim(), lignes: 0 });
        else if (el.tagName === 'TABLE' && blocs.length) blocs[blocs.length - 1].lignes = el.querySelectorAll('tbody tr').length;
      });
      return {
        scrollHeight: body.scrollHeight,
        clientHeight: body.clientHeight,
        dernier: pageEl.lastElementChild ? pageEl.lastElementChild.className : '',
        basCartouche: cartouche ? cartouche.getBoundingClientRect().bottom : NaN,
        basPage: rectPage.bottom - bordBas,
        meta: (pageEl.querySelector('.rep-meta') || {}).textContent || '',
        blocs,
      };
    }));

    const total = mesure.length;
    assert.ok(total >= 2, `24 portes a designations longues : plusieurs pages attendues, ${total} obtenue(s)`);
    mesure.forEach((p, i) => {
      assert.ok(p.scrollHeight <= p.clientHeight + 1, `page ${i + 1} : contenu deborde (${p.scrollHeight} > ${p.clientHeight})`);
      assert.match(p.dernier, /\brep-cartouche\b/, `page ${i + 1} : le cartouche doit etre le dernier element`);
      assert.ok(Math.abs(p.basCartouche - p.basPage) <= 1, `page ${i + 1} : cartouche decolle du bas (${p.basCartouche} / ${p.basPage})`);
      assert.match(p.meta, new RegExp(`Page ${i + 1}/${total}(?!\\d)`), `page ${i + 1} : pagination`);
    });

    const blocs = mesure.flatMap(p => p.blocs);
    const base = titre => titre.replace(/\s*\(suite\)$/, '');
    const sections = [...new Set(blocs.map(b => base(b.titre)))];
    assert.equal(sections.length, 3, `3 sections attendues : ${sections.join(' | ')}`);
    sections.forEach(section => {
      const siens = blocs.filter(b => base(b.titre) === section);
      assert.ok(!/\(suite\)$/.test(siens[0].titre), `${section} : le premier bloc n'est pas une suite`);
      siens.slice(1).forEach(b => assert.match(b.titre, /\(suite\)$/, `${section} : bloc coupe sans « (suite) »`));
      assert.equal(siens.reduce((s, b) => s + b.lignes, 0), 24, `${section} : 24 lignes au total`);
    });
    assert.ok(blocs.some(b => /\(suite\)$/.test(b.titre)), 'au moins une section coupee attendue avec 24 portes');
  });
});

test('E10c PDF de reperage sans porte active : aucune fenetre ouverte', OPTIONS, async () => {
  await avecPage(fx.fixtureSansPorteActive(TIL), async ({ context, page }) => {
    const ouvertes = [];
    context.on('page', p => ouvertes.push(p));
    await page.evaluate(() => exporterListePortesPdf());
    await page.waitForTimeout(500);
    assert.equal(ouvertes.length, 0, 'aucune popup attendue sans porte active');
  });
});

test('E11 fiche detail porte : lecteur de sortie, registres au numero de lecteur', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const fiche = async num => page.evaluate(n => {
      voirDetailPorte(n, 0);
      const body = document.getElementById('modal-body');
      const lignes = [...body.querySelectorAll('.detail-row')].map(row => [
        (row.querySelector('.detail-key') || {}).textContent?.trim() || '',
        (row.querySelector('.detail-val') || {}).textContent?.trim() || '',
      ]);
      return {
        sousTitre: document.getElementById('modal-subtitle').textContent.trim(),
        texte: body.textContent.replace(/\s+/g, ' '),
        lignes,
      };
    }, num);

    const p2 = await fiche(2);
    assert.ok(p2.sousTitre.endsWith('LA3 · LA4'), `sous-titre porte 2 : ${p2.sousTitre}`);
    assert.ok(p2.texte.includes('TN3=300'), 'porte 2 : TN3=300 attendu');
    assert.ok(!p2.texte.includes('TN2='), 'porte 2 : TN2= ne doit pas apparaitre');
    ['LED Verte sortie (LA4)', 'XA0306', 'XA0307', 'XA0308'].forEach(valeur => {
      assert.ok(p2.texte.includes(valeur), `porte 2 : « ${valeur} » attendu`);
    });

    const p3 = await fiche(3);
    assert.ok(p3.texte.includes('TN2=300'), 'porte 3 : TN2=300 attendu');
    assert.ok(p3.sousTitre.endsWith('LA2'), `sous-titre porte 3 : ${p3.sousTitre}`);

    const p1 = await fiche(1);
    const valeur = cle => (p1.lignes.find(([k]) => k === cle) || [])[1];
    assert.equal(valeur('Bouton Poussoir'), 'DA0101', 'porte 1 : BP');
    assert.equal(valeur('Déclencheur manuel'), 'DA0103', 'porte 1 : DM');
  });
});

test('E12 schema de cablage : la porte a deux lecteurs cable sa sortie sur L2', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const schema = num => page.evaluate(n => {
      voirDetailPorte(n, 0);
      if (typeof closeWiringUsagePopup === 'function') closeWiringUsagePopup();
      const svg = document.querySelector('#modal-body .door-wiring-svg');
      const cles = [...svg.querySelectorAll('[data-seg="reader-line"]')].map(e => e.dataset.key);
      const lignes = [...document.querySelectorAll('#modal-body .door-wire-row')].map(r => r.textContent.replace(/\s+/g, ' ').trim());
      fermerModal();
      return { bornes: [...new Set(cles)].map(k => k.split(':').pop()), lignes };
    }, num);

    const p2 = await schema(2);
    assert.deepEqual(p2.bornes, ['L1', 'L2'], 'porte 2 : un cable lecteur sur L1 et un sur L2');
    assert.ok(p2.lignes.some(l => l.includes('Lecteur de sortie') && l.includes('LA4') && l.includes('L2')), `porte 2 : ligne lecteur de sortie LA4 sur L2 absente : ${p2.lignes.join(' / ')}`);
    assert.ok(p2.lignes.some(l => l.includes("Lecteur d'entrée") && l.includes('LA3') && l.includes('L1')), 'porte 2 : lecteur d\'entree LA3 sur L1');

    const p1 = await schema(1);
    assert.deepEqual(p1.bornes, ['L1'], 'porte 1 (un lecteur) : seulement L1');
    const p3 = await schema(3);
    assert.deepEqual(p3.bornes, ['L2'], 'porte 3 (2e tete) : seulement L2');

    // La couleur du cable de sortie est independante de celle de l'entree.
    const couleurs = await page.evaluate(() => {
      const porte = getTillysActif().portes[1];
      _applyColorToPorte(porte, 'readerOut', 'Vert', 'Noir');
      return { sortie: porte.wiringConfig.readerOut.color, entree: porte.wiringConfig.reader.color };
    });
    assert.equal(couleurs.sortie, 'Vert');
    assert.notEqual(couleurs.entree, 'Vert');
  });
});

test('E13 export Excel liste des portes : une seule feuille, lecteur de sortie compris', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const resultat = await page.evaluate(() => {
      let classeur = null;
      XLSX.writeFile = wb => { classeur = wb; };
      exporterListePortesExcel();
      return {
        feuilles: classeur.SheetNames,
        lignes: XLSX.utils.sheet_to_json(classeur.Sheets[classeur.SheetNames[0]], { header: 1, defval: '' }),
      };
    });
    assert.deepEqual(resultat.feuilles, ['LISTE DE PORTE'], 'l\'export ne contient que la liste des portes');
    const hall = resultat.lignes.find(l => l.includes('Hall'));
    assert.ok(hall, 'ligne du Hall absente');
    assert.equal(hall.filter(v => v === 'LB').length, 2, 'Hall : lecteur LB en entree et en sortie');
  });
});

test('E14 export Excel auto-control : feuille unique, statuts et couleurs du projet', { timeout: 90000 }, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const base64 = await page.evaluate(async () => {
      const snapshot = getAutoControlSnapshot();
      const rows = getAutoControlRows(snapshot);
      const porte1 = getAutoControlRecord(rows[0].key);
      porte1.etatGeneral = 'C';
      porte1.bp = 'NC';
      porte1.commentaires = 'BP a remplacer';
      porte1.dmExempt = 'X';
      getAutoControlRecord(rows[1].key).etatGeneral = 'NV';
      const reponse = await fetch(getAutoControlExportEndpoint(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildAutoControlTemplateExportPayload(snapshot, rows)),
      });
      if (!reponse.ok) return 'HTTP ' + reponse.status + ' ' + await reponse.text();
      const octets = new Uint8Array(await reponse.arrayBuffer());
      let texte = '';
      for (let i = 0; i < octets.length; i += 1) texte += String.fromCharCode(octets[i]);
      return btoa(texte);
    });
    assert.ok(!base64.startsWith('HTTP'), base64.slice(0, 300));
    const XLSXN = require(require('path').join(require('./helpers/racine').getRacineApp(), 'app', 'vendor', 'xlsx.full.min.js'));
    const wb = XLSXN.read(Buffer.from(base64, 'base64'), { bookVBA: true, cellStyles: true });
    assert.deepEqual(wb.SheetNames, ['Fiche auto control'], 'une seule feuille');
    assert.ok(!wb.vbaraw, 'pas de macros dans l\'export');
    const ws = wb.Sheets['Fiche auto control'];
    const valeur = ref => (ws[ref] && ws[ref].v) || '';
    const fond = ref => (ws[ref] && ws[ref].s && ws[ref].s.patternType === 'solid' && ws[ref].s.fgColor && ws[ref].s.fgColor.rgb) || '';

    // Porte 1 (ligne 15) : statuts saisis, DM exempte en gris, commentaire du projet.
    assert.equal(valeur('B15'), 'Local Velos');
    assert.deepEqual([valeur('E15'), valeur('J15'), valeur('T15')], ['C', 'NC', 'BP a remplacer']);
    assert.equal(valeur('G15'), '', 'DM exempte : pas de statut');
    assert.equal(fond('G15'), 'D9D9D9', 'DM exempte : gris de l\'application');
    // Seules les cases exemptees ou les bandeaux de section portent un fond dans la zone des portes.
    const autres = Object.keys(ws)
      .filter(ref => ref[0] !== '!')
      .filter(ref => {
        const ligne = Number(ref.replace(/[A-Z]+/, ''));
        return ligne >= 15 && ligne <= 270 && fond(ref) && ref !== 'G15' && !/^[A-Z]+14$/.test(ref);
      });
    assert.deepEqual(autres.slice(0, 10), [], 'couleurs qui ne viennent pas du projet');
    // Aucun reste de l'exemple du modele.
    const texte = Object.keys(ws).filter(ref => ref[0] !== '!').map(ref => String(ws[ref].v || '')).join(' ');
    assert.ok(!/SARTOR|P17|LUDO/i.test(texte), 'donnees de l\'ancien chantier dans l\'export');
  });
});

// ── APERIO et biometrie (plan « APERIO + biometrie » : E15 a E23) ─────────

// Lignes du tableau d'adresses rendu, indexees par numero de porte.
async function tableauAdresses(page) {
  const lignes = await page.evaluate(() => {
    renderTableauAdresses();
    return [...document.querySelectorAll('#addr-tbody tr')]
      .map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.replace(/\s+/g, ' ').trim()));
  });
  return num => lignes.find(cellules => cellules[0] === String(num).padStart(2, '0'));
}

test('E15 tableau d\'adresses : porte APERIO 3 sans relais, LED sur la tete LA2 ; porte 1 inchangee', OPTIONS, async () => {
  await avecPage(fx.fixtureAperio(TIL), async ({ page }) => {
    const porte = await tableauAdresses(page);
    const p3 = porte(3);
    assert.ok(p3, 'ligne de la porte 3 absente');
    assert.equal(p3[7], 'APERIO', 'serrure porte 3');
    assert.equal(p3[8], 'APERIO', 'colonne Relais : APERIO au lieu d\'un registre relais');
    assert.equal(p3[9], 'XA0203', 'LED Verte = ouverture APERIO');
    assert.equal(p3[10], 'XA0204', 'LED Rouge = refus APERIO');
    assert.ok(['', '—'].includes(p3[11]), `porte APERIO : pas de buzzer, obtenu « ${p3[11]} »`);
    assert.deepEqual(porte(1).slice(8, 12), ['XA0101', 'XA0103', 'XA0104', 'XA0105'], 'porte 1 ventouse inchangee');
  });
});

test('E16 export CSV : porte APERIO 3 => Relais APERIO, LED XA0203 / XA0204, Buzzer vide', OPTIONS, async () => {
  await avecPage(fx.fixtureAperio(TIL), async ({ page }) => {
    const csv = await page.evaluate(() => {
      window.__csv = null;
      window.telechargerContenu = contenu => { window.__csv = contenu; };
      exporterCSV();
      return window.__csv;
    });
    assert.equal(typeof csv, 'string', 'exporterCSV doit produire un contenu');
    const lignes = csv.split(/\r?\n/).filter(Boolean).map(l => l.split(';'));
    const entetes = lignes[0];
    const porte3 = lignes.find(c => c[1] === '3');
    assert.ok(porte3, 'ligne de la porte 3 absente du CSV');
    const col = nom => porte3[entetes.indexOf(nom)];
    assert.equal(col('Relais'), 'APERIO');
    assert.equal(col('LED Verte'), 'XA0203');
    assert.equal(col('LED Rouge'), 'XA0204');
    assert.equal(col('Buzzer'), '', 'porte APERIO : buzzer vide');
  });
});

test('E17 fiche detail de la porte APERIO 3 : type de serrure APERIO, pas « Libre »', OPTIONS, async () => {
  await avecPage(fx.fixtureAperio(TIL), async ({ page }) => {
    const lignes = await page.evaluate(() => {
      voirDetailPorte(3, 0);
      if (typeof closeWiringUsagePopup === 'function') closeWiringUsagePopup();
      return [...document.querySelectorAll('#modal-body .detail-row')].map(row => [
        (row.querySelector('.detail-key') || {}).textContent?.trim() || '',
        (row.querySelector('.detail-val') || {}).textContent?.replace(/\s+/g, ' ').trim() || '',
      ]);
    });
    const valeur = cle => (lignes.find(([k]) => k === cle) || [])[1];
    const type = valeur('Type de serrure') || '';
    assert.match(type, /APERIO/, `type de serrure : « ${type} »`);
    assert.doesNotMatch(type, /Libre/i, `type de serrure : « ${type} »`);
    assert.equal(valeur('Gâche / Serrure'), 'APERIO', 'sortie serrure : APERIO, pas de relais');
    assert.equal(valeur('LED Verte'), 'XA0203');
  });
});

test('E18 schema de cablage de la porte APERIO 3 : serrure APERIO au niveau du relais, sans cable relais ni lecteur', OPTIONS, async () => {
  await avecPage(fx.fixtureAperio(TIL), async ({ page }) => {
    const schema = await page.evaluate(() => {
      voirDetailPorte(3, 0);
      if (typeof closeWiringUsagePopup === 'function') closeWiringUsagePopup();
      const svg = document.querySelector('#modal-body .door-wiring-svg');
      const lock = svg && svg.querySelector('.io-label-g[data-wiring-kind="lock"]');
      const rangees = [...document.querySelectorAll('#modal-body .door-wire-row')].map(r => ({
        borne: (r.querySelector('.door-wire-node.module span') || {}).textContent?.trim() || '',
        texte: r.textContent.replace(/\s+/g, ' ').trim(),
      }));
      return {
        svg: !!svg,
        lock: lock ? lock.textContent.replace(/\s+/g, ' ').trim() : null,
        cableB: svg ? svg.querySelectorAll('polyline[data-seg="b"][data-key="3:R2"]').length : -1,
        relayRef: svg ? svg.querySelectorAll('[data-seg="relay-ref"][data-key="rr:3:R2"]').length : -1,
        lecteur: svg ? svg.querySelectorAll('[data-seg="reader-line"]').length : -1,
        r2: rangees.filter(r => r.borne === 'R2').map(r => r.texte),
      };
    });
    assert.ok(schema.svg, 'precondition : schema de cablage de la porte 3 rendu');
    assert.ok(schema.lock, 'etiquette de la serrure (data-wiring-kind="lock") absente du schema');
    assert.match(schema.lock, /SERRURE APERIO/, `etiquette serrure : ${schema.lock}`);
    assert.doesNotMatch(schema.lock, /CMD/, `etiquette serrure : ${schema.lock}`);
    assert.equal(schema.cableB, 0, 'aucun cable relais (data-seg="b") sur R2 pour une serrure APERIO');
    assert.equal(schema.relayRef, 0, 'aucun commun relais (relay-ref) sur R2 pour une serrure APERIO');
    assert.equal(schema.lecteur, 0, 'aucun cable lecteur : la tete APERIO est dans la serrure');
    assert.ok(schema.r2.length === 1 && /SERRURE APERIO/.test(schema.r2[0]), `rangee R2 : ${schema.r2.join(' / ')}`);
  });
});

test('E19 schema MLP2 A1 fusionne : R1 (porte 1) cable, R2 (porte 3 APERIO) sans cable relais ni lecteur', OPTIONS, async () => {
  await avecPage(fx.fixtureAperio(TIL), async ({ page }) => {
    const vue = await page.evaluate(() => {
      const t = APP.tillys[0];
      const ma1 = t.synopticModules.find(m => m.id === 'MA1');
      const tpl = document.createElement('template');
      tpl.innerHTML = renderModuleCombinedWiringSection(t, 0, ma1);
      const svg = tpl.content.querySelector('svg');
      const compte = sel => (svg ? svg.querySelectorAll(sel).length : -1);
      const lock3 = svg && svg.querySelector('.io-label-g[data-wiring-kind="lock"][data-wiring-door-num="3"]');
      return {
        svg: !!svg,
        b1: compte('polyline[data-seg="b"][data-key="MA1:R1"]'),
        rr1: compte('[data-seg="relay-ref"][data-key="rr:MA1:R1"]'),
        b2: compte('polyline[data-seg="b"][data-key="MA1:R2"]'),
        rr2: compte('[data-seg="relay-ref"][data-key="rr:MA1:R2"]'),
        l1: compte('[data-seg="reader-line"][data-key="MA1:L1"]'),
        l2: compte('[data-seg="reader-line"][data-key="MA1:L2"]'),
        lock3: lock3 ? lock3.textContent.replace(/\s+/g, ' ').trim() : null,
      };
    });
    assert.ok(vue.svg, 'precondition : schema fusionne rendu');
    assert.ok(vue.b1 > 0, 'porte 1 : cable relais R1 conserve');
    assert.ok(vue.rr1 > 0, 'porte 1 : commun relais R1 conserve');
    assert.ok(vue.l1 > 0, 'porte 1 : cable lecteur L1 conserve');
    assert.equal(vue.b2, 0, 'porte 3 APERIO : aucun cable relais R2');
    assert.equal(vue.rr2, 0, 'porte 3 APERIO : aucun commun relais R2');
    assert.equal(vue.l2, 0, 'porte 3 APERIO : aucun cable lecteur L2');
    assert.ok(vue.lock3, 'etiquette serrure de la porte 3 absente du schema fusionne');
    assert.match(vue.lock3, /SERRURE APERIO/, `etiquette serrure porte 3 : ${vue.lock3}`);
  });
});

test('E20 carnet de cables : HUB APERIO en Cat 6/6A/7 a la place de la CMD, pas de cable lecteur', OPTIONS, async () => {
  await avecPage(fx.fixtureAperio(TIL), async ({ page }) => {
    // Lecture seule des lignes calculees : aucun export Excel declenche.
    const lignes = await page.evaluate(() => buildCarnetCableRows()
      .map(r => ({ code: r.codeDepart, depart: r.depart, type: r.typeCableDepart, arrivee: r.arrivee })));
    const ligne = code => lignes.find(l => l.code === code);
    const porte3 = lignes.filter(l => /A_N0_3$/.test(l.code) || l.code === 'LA2' || l.arrivee === 'LA2').map(l => l.code).sort();
    assert.ok(!ligne('CMD A_N0_3'), 'porte APERIO : plus de ligne CMD A_N0_3');
    const hub = ligne('HUB APERIO A_N0_3');
    assert.ok(hub, `ligne HUB APERIO A_N0_3 absente : ${lignes.map(l => l.code).join(' | ')}`);
    assert.equal(hub.type, 'Cat 6/6A/7');
    assert.match(hub.depart, /Tillys 1/, 'le HUB APERIO part du coffret / Tillys');
    assert.deepEqual(porte3, ['BP A_N0_3', 'HUB APERIO A_N0_3'], 'porte 3 : HUB APERIO et BP, aucun cable lecteur');
    const cmd1 = ligne('CMD A_N0_1');
    assert.ok(cmd1, 'ligne CMD A_N0_1 absente');
    assert.equal(cmd1.depart, 'BJ A_N0_1', 'porte 1 inchangee : CMD depuis la boite de jonction');
  });
});

test('E21 editeur de porte : choisir le verrouillage APERIO met le lecteur APERIO et retire le lecteur de sortie', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const choisirAperio = num => page.evaluate(n => {
      ouvrirPorteEditor(n);
      updatePorteDraft('verrouillage', 'APERIO');
      const brouillon = { lecteurEntree: PORTES_UI.editingDraft.lecteurEntree, lecteurSortie: PORTES_UI.editingDraft.lecteurSortie };
      validerPorteEditor();
      const porte = getTillysActif().portes[n - 1];
      fermerPorteEditor();
      return { brouillon, verrouillage: porte.verrouillage, lecteurEntree: porte.lecteurEntree, lecteurSortie: porte.lecteurSortie };
    }, num);

    const p3 = await choisirAperio(3);
    assert.equal(p3.verrouillage, 'APERIO', 'precondition : verrouillage APERIO enregistre');
    assert.equal(p3.brouillon.lecteurEntree, 'APERIO', 'brouillon : lecteur d\'entree APERIO');
    assert.equal(p3.lecteurEntree, 'APERIO', 'porte 3 : lecteur d\'entree APERIO');
    assert.equal(p3.lecteurSortie, '', 'porte 3 : pas de lecteur de sortie');

    const p2 = await choisirAperio(2);
    assert.equal(p2.lecteurEntree, 'APERIO', 'porte 2 : lecteur d\'entree APERIO');
    assert.equal(p2.lecteurSortie, '', 'porte 2 (deux lecteurs) : lecteur de sortie retire');
  });
});

test('E22 generation du code dans la page : APERIO_OPEN puis BIO_STATUS, sans erreur', OPTIONS, async () => {
  await avecPage(fx.fixtureAperio(TIL), async ({ page, erreurs }) => {
    const aperio = await page.evaluate(() => { genererTout(); return document.getElementById('microcode-output').value; });
    assert.ok(aperio.includes('APERIO_OPEN('), 'microcode APERIO sans APERIO_OPEN(');
    await chargerTillys(page, fx.fixtureBio(TIL));
    const bio = await page.evaluate(() => { genererTout(); return document.getElementById('microcode-output').value; });
    assert.ok(bio.includes('BIO_STATUS_B6'), 'microcode biometrique sans BIO_STATUS_B6');
    assert.deepEqual(erreurs.map(e => e.message), []);
  });
});

test('E23 (non-regression) consommation coffret : porte APERIO 130 mA, lecteur biometrique 360 mA', OPTIONS, async () => {
  await avecPage(fx.fixtureAperio(TIL), async ({ page }) => {
    const total = await page.evaluate(() => getCoffretDoorEquipmentItems(APP.tillys[0].portes[2])
      .reduce((somme, item) => somme + item.chargeMa, 0));
    assert.equal(total, 130, 'porte 3 APERIO : lecteur APERIO 130 mA, serrure APERIO 0 mA');
  });
  await avecPage(fx.fixtureBio(TIL), async ({ page }) => {
    const lecteur = await page.evaluate(() => getCoffretDoorEquipmentItems(APP.tillys[0].portes[7])
      .find(item => item.type === 'Lecteur entrée'));
    assert.ok(lecteur, 'porte 8 : lecteur d\'entree absent du bilan');
    assert.equal(lecteur.chargeMa, 360, 'lecteur biometrique : 360 mA');
  });
});

// ── Revue APERIO : retour arriere, lecteur de sortie, synoptique ─────────

test('E24 editeur : APERIO puis retour a VENTOUSE => la porte 3 redevient une porte a relais', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const etat = await page.evaluate(() => {
      ouvrirPorteEditor(3);
      updatePorteDraft('verrouillage', 'APERIO');
      const intermediaire = PORTES_UI.editingDraft.lecteurEntree;
      updatePorteDraft('verrouillage', 'VENTOUSE');
      validerPorteEditor();
      fermerPorteEditor();
      const t = getTillysActif();
      const porte = t.portes[2];
      const addr = TIL.getPorteAddresses(t, 3);
      genererTout();
      const microcode = document.getElementById('microcode-output').value;
      voirDetailPorte(3, 0);
      if (typeof closeWiringUsagePopup === 'function') closeWiringUsagePopup();
      const svg = document.querySelector('#modal-body .door-wiring-svg');
      return {
        intermediaire,
        verrouillage: porte.verrouillage,
        lecteurEntree: porte.lecteurEntree,
        aperio: addr.aperio,
        lock: addr.lock,
        microcode,
        svg: svg ? svg.textContent.replace(/\s+/g, ' ') : null,
      };
    });
    assert.equal(etat.intermediaire, 'APERIO', 'precondition : le choix APERIO pose le lecteur APERIO');
    assert.equal(etat.verrouillage, 'VENTOUSE', 'precondition : verrouillage VENTOUSE enregistre');
    assert.equal(etat.lecteurEntree, 'LB', 'retour a VENTOUSE : le lecteur d\'entree redevient LB');
    assert.equal(etat.aperio, false, 'retour a VENTOUSE : la porte 3 n\'est plus APERIO');
    assert.equal(etat.lock, 'XA0102', 'retour a VENTOUSE : relais normal XA0102');
    assert.ok(etat.microcode.includes('XA0102=PULSE('), 'microcode : ouverture par le relais XA0102=PULSE( attendue');
    assert.ok(etat.svg, 'precondition : schema de cablage de la porte 3 rendu');
    assert.ok(!etat.svg.includes('SERRURE APERIO'), `schema de la porte 3 encore en SERRURE APERIO : ${etat.svg}`);
  });
});

test('E25 editeur : un lecteur de sortie choisi sur une porte APERIO n\'est pas enregistre', OPTIONS, async () => {
  await avecPage(fx.fixtureAperio(TIL), async ({ page }) => {
    const porte = await page.evaluate(() => {
      ouvrirPorteEditor(6);
      updatePorteDraft('lecteurSortie', 'LB');
      validerPorteEditor();
      fermerPorteEditor();
      const p = getTillysActif().portes[5];
      return { verrouillage: p.verrouillage, lecteurEntree: p.lecteurEntree, lecteurSortie: p.lecteurSortie };
    });
    assert.equal(porte.verrouillage, 'APERIO', 'precondition : porte 6 toujours APERIO');
    assert.equal(porte.lecteurSortie, '', 'porte APERIO : lecteur de sortie retire a la validation');
  });
});

test('E26 porte APERIO chargee avec un lecteur de sortie : ni consommation de sortie ni seconde tete au synoptique', OPTIONS, async () => {
  const t = fx.fixtureAperio(TIL);
  t.portes[5].lecteurSortie = 'LB';
  await avecPage(t, async ({ page }) => {
    const vue = await page.evaluate(() => {
      const tillys = APP.tillys[0];
      const porte = tillys.portes[5];
      const ma5 = tillys.synopticModules.find(m => m.id === 'MA5');
      return {
        verrouillage: porte.verrouillage,
        types: getCoffretDoorEquipmentItems(porte).map(item => item.type),
        tetes: getPorteSynopticReaderLabels(porte, 6, tillys, ma5),
      };
    });
    assert.equal(vue.verrouillage, 'APERIO', 'precondition : porte 6 chargee en APERIO');
    assert.ok(vue.types.includes('Lecteur entrée'), `precondition : lecteur APERIO au bilan : ${vue.types.join(' | ')}`);
    assert.ok(!vue.types.includes('Lecteur sortie'), `porte APERIO : « Lecteur sortie » compte au bilan coffret : ${vue.types.join(' | ')}`);
    assert.deepEqual(vue.tetes, ['LA5'], 'porte APERIO : une seule tete au synoptique');
  });
});

test('E27 synoptique : la carte de la porte APERIO 6 affiche APERIO, pas « libre »', OPTIONS, async () => {
  const t = fx.fixtureAperio(TIL);
  // Designations sans le mot APERIO : seul l'affichage de la serrure peut le montrer.
  t.portes[5].designation = 'Bureau direction';
  await avecPage(t, async ({ page }) => {
    const cartes = await page.evaluate(() => {
      showTab('tab-synoptic');
      renderSynoptique();
      const texte = num => [...document.querySelectorAll(`#synoptic-root [data-drag-porte-num="${num}"]`)]
        .map(el => el.textContent.replace(/\s+/g, ' ').trim());
      return { porte6: texte(6), porte1: texte(1) };
    });
    assert.ok(cartes.porte6.length > 0, 'precondition : carte de la porte 6 rendue dans le synoptique');
    cartes.porte6.forEach(texte => {
      assert.ok(texte.includes('Bureau direction'), `precondition : carte de la porte 6 : ${texte}`);
      assert.match(texte, /APERIO/, `carte de la porte APERIO 6 sans « APERIO » : ${texte}`);
      assert.ok(!texte.includes('🔓'), `carte de la porte APERIO 6 avec l'icone libre : ${texte}`);
      assert.doesNotMatch(texte, /libre/i, `carte de la porte APERIO 6 en « libre » : ${texte}`);
    });
    cartes.porte1.forEach(texte => assert.doesNotMatch(texte, /APERIO/, `porte 1 ventouse marquee APERIO : ${texte}`));
  });
});

test('E28 porte APERIO chargee avec un lecteur de sortie : la sortie est retiree des donnees et de l\'auto-control', OPTIONS, async () => {
  const t = fx.fixtureAperio(TIL);
  t.portes[5].lecteurSortie = 'LB';
  t.portes[5].numeroSortie = '099';
  t.portes[0].lecteurSortie = 'LB';
  await avecPage(t, async ({ page }) => {
    const vue = await page.evaluate(() => {
      const tillys = APP.tillys[0];
      const rows = getAutoControlRows(getAutoControlSnapshot());
      const lecteurs = num => {
        // L'auto-control travaille sur une copie du projet : on cherche la ligne par numero de porte.
        const row = rows.find(r => r.porte && r.porte.num === num);
        return row ? getAutoControlConfiguredReaders(row).map(r => r.readerDirection) : null;
      };
      return {
        sortieAperio: tillys.portes[5].lecteurSortie,
        sortieVentouse: tillys.portes[0].lecteurSortie,
        autoControlAperio: lecteurs(6),
        autoControlVentouse: lecteurs(1),
      };
    });
    assert.equal(vue.sortieAperio, '', 'porte APERIO : lecteur de sortie retire au chargement');
    assert.deepEqual(vue.autoControlAperio, ['Entrée'], 'auto-control : un seul lecteur pour la porte APERIO');
    assert.equal(vue.sortieVentouse, 'LB', 'non-regression : une porte a relais garde son lecteur de sortie');
    assert.deepEqual(vue.autoControlVentouse, ['Entrée', 'Sortie'], 'non-regression : auto-control de la porte a relais');
  });
});
