"""Vornamen-Wächter (Chef 29.08.2026): Geschlecht aus dem Vornamen bestimmen,
damit die Stimme den Anrufer als "Herr X" / "Frau X" anspricht und die neue
Kartei das Geschlecht gleich richtig trägt.

Regeln:
- Kuratierte Listen häufiger Vornamen (deutsch + gängige griechische,
  türkische, slawische, südeuropäische Namen — Praxis-Klientel).
- Uneindeutige Namen (Kim, Luca, Toni …) liefern "" — der Aufrufer setzt
  dann den Chef-Default WEIBLICH und vermerkt "bitte Geschlecht prüfen"
  in der Termin-Notiz.
- Ein Kartei-Eintrag (gender aus Pickadoc) schlägt IMMER die Schätzung —
  das regelt der Aufrufer (gehirn/hintergrund), nicht dieses Modul.
"""

from __future__ import annotations

_M = frozenset("""
alexander andreas albert alfred anton armin arne arno axel bastian benedikt
benjamin bernd bernhard bert bjoern björn bodo boris bruno carl carsten
christian christoph clemens conrad constantin cornelius daniel david dennis
detlef dieter dietmar dietrich dirk dominik eberhard eckhard edgar eduard
egon elias emil enno erhard eric erik ernst erwin eugen fabian falk felix
ferdinand florian frank franz fred frederik friedrich fritz gabriel georg
gerald gerd gerhard gernot gottfried gregor guenter guenther gunnar gustav
hagen hannes hans harald hartmut heiko heiner heinrich heinz helge helmut
hendrik henning henrik herbert hermann holger horst hubert hugo ingo jakob
jan jannik jano jason jens joachim jochen johann johannes jonas jonathan
joerg jörg josef joseph joshua juergen jürgen julian julius justus kai karl
karsten kaspar kevin kilian klaus konrad konstantin kurt lars laurenz lennard
lennart leo leon leonard leonhard levi liam linus lorenz lothar ludwig lukas
lutz magnus maik malte manfred manuel marcel marco marcus mario mark marko
markus martin marvin mathias matthias mats max maximilian mehmet michael
mika milan mirko moritz mustafa nick niclas nico nicolas niels niklas nils
noah norbert norman ole oliver olaf oskar oswald otto pascal patrick paul
peter phil philip philipp pierre rafael raik rainer ralf ralph raphael
reiner reinhard rene renee ricardo richard robert roland rolf roman ronald
ronny ruben rudi rudolf ruediger rüdiger rupert sam samuel sebastian
siegfried simon soeren sören stefan steffen stephan sven theo theodor thomas
thorben thorsten til till tim timo tobias tom torben torsten udo ulf ulrich
uwe valentin veit victor viktor vincent volker waldemar walter werner
wilfried wilhelm willi wolf wolfgang xaver yannick yannik
achim adem ahmet ali aloys andré andre ansgar aris aristoteles burak can
cem christos claus deniz dimitri dimitrios emre enes fatih giannis giorgos
gerrit hakan halil hasan hussein ibrahim igor ilias ioannis ivan jorgos
kemal konstantinos kostas laurin levent luka marek mateusz mert milos mirco
murat mihail michalis nikolaos nikos omar osman panagiotis pavel pawel petar
petros piotr sergej spiros stavros stefanos taner tarik theodoros vassilis
vasilis yannis yusuf
""".split())

_F = frozenset("""
alexandra alina amelie andrea anette angela angelika anja anke anna annalena
anne annegret annelie annette annika antje antonia astrid barbara bianca
birgit brigitte britta camilla carina carla carmen carolin caroline cathrin
celine charlotte christa christel christiane christin christina christine
claudia clara constanze cornelia dagmar daniela diana doris dorothea edith
elena eleni elfriede elisa elisabeth elke ella emilia emma erika erna esther
eva evelyn fabienne felicitas fiona franziska frauke frieda friederike
gabriele gerda gertrud gisela greta gudrun hanna hannah hannelore heide
heidi heike helene helga henrike hertha hilde hildegard ilse ines inga inge
ingeborg ingrid irene iris irmgard isabel isabell isabella isabelle jana
janina janine jasmin jennifer jessica johanna judith julia juliane jutta
karin karla karola katarina katharina kathrin katja katrin kerstin kirsten
klara kristin lara laura lea lena leni leonie lieselotte lilli lilly lina
linda lisa lisbeth lotte louisa luisa luise madeleine magdalena maja
manuela mara mareike margarete margit margot margret maria marianne marie
marina marion marlene marlies marta martha martina mathilda mathilde meike
melanie melina melissa merle mia michaela mila milena miriam mona monika
nadine nadja natalia natalie nele nicole nina nora olga pauline petra pia
ramona rebecca regina renate rita romy rosa rosemarie rosi ruth sabine
sabrina sandra sara sarah saskia selina sigrid silke silvia simone sina
sofia sofie sonja sophia sophie stefanie steffi stephanie susanne svenja
sylvia tanja tatjana thea theresa therese tina traudel ulla ulrike ursel
ursula ute uta valentina vanessa vera verena veronika viktoria viola
waltraud wilhelmine yvonne
aische anastasia aylin ayse büsra buesra defne despina dilara ebru ekaterini
elif eleftheria emine esra fatima fatma georgia hatice irini ivana jelena
katerina konstantina leyla ludmilla melek meltem merve milica mirjana nazan
oksana olena panagiota paraskevi selin semra sevim songül songuel svetlana
tugba vasiliki zeynep zoe
""".split())

# Im Deutschen wirklich UNEINDEUTIGE Vornamen: nie raten, Default regelt
# der Aufrufer (weiblich + Notiz an die Praxis).
_AMBIG = frozenset("""
alexis andy ari ashley charlie chris dana dominique elia eike gabi jamie
jona jules kim luca lucca maxime mica micha nicola nikita noa robin sam
sascha sasha toni yuki
""".split())


def _norm(name: str) -> str:
    t = " ".join(str(name or "").split()).strip().lower()
    t = t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    # Doppelnamen ("Hans-Peter", "Anna Lena"): der ERSTE Teil entscheidet.
    for trenn in ("-", " "):
        if trenn in t:
            t = t.split(trenn)[0]
    return t


def geschlecht(vorname: str) -> str:
    """'m', 'f' oder '' (unklar). Nie raten bei mehrdeutigen Namen."""
    n = _norm(vorname)
    if not n or n in _AMBIG:
        return ""
    # Listen zuerst — auch für den umlaut-normalisierten Vergleich.
    if n in _M and n not in _F:
        return "m"
    if n in _F and n not in _M:
        return "f"
    if n in _M and n in _F:
        return ""
    # Konservative Endungs-Heuristik NUR für ungelistete Namen: -a ist im
    # Deutschen fast immer weiblich (Ausnahmen wie Joshua/Luca stehen oben).
    if len(n) >= 3 and n.endswith("a"):
        return "f"
    return ""
