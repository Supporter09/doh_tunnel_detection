<!-- ppt-master-schema: spec-lock/v1 -->
# Execution Lock

## canvas
- viewBox: 0 0 1280 720
- format: PPT 16:9

## communication
- primary_language: en-US
- audience: Faculty members and academic evaluators with technical literacy in networking, cybersecurity, and machine learning
- objective: Explain the original method, prove the reproduction, expose leakage risk, and enable a bounded judgment of the BiGRU improvement
- core_message: Under a capped session-disjoint run, mask-aware BiGRU improves best-window F1 by 4.73 pp on L1 and 4.40 pp on L2 without establishing full-dataset convergence
- consumption_mode: balanced

## mode
- mode: custom
- mode_references: pyramid, instructional
- mode_behavior: Lead with the evidence-backed conclusion, then teach the packet-clump method and evaluation protocol in dependency order; every results page states the finding before its supporting metric and caveat.

## visual_style
- visual_style: custom
- visual_style_references: data-journalism, swiss-minimal
- visual_style_behavior: Use publication-grade metric hierarchy, source lines, and chart-led pages on a rigorous asymmetric Swiss grid; large light fields, sharp geometry, hairline dividers, and sparse semantic accents replace decorative cards.

## colors
- background: #F7F9FC
- secondary_bg: #EAF0F5
- primary: #14324B
- accent: #0E7490
- secondary_accent: #D97706
- body_text: #172033
- secondary_text: #5B6875
- divider: #C9D3DC
- surface: #FFFFFF
- positive: #15803D
- negative: #B42318

## typography
- font_family: Aptos, Arial
- title_family: Aptos Display, Arial
- body_family: Aptos, Arial
- data_family: Consolas, Courier New
- code_family: Consolas, Courier New
- body: 24
- title: 42
- subtitle: 30
- lead: 28
- annotation: 18
- footnote: 14
- data: 20
- code: 18
- display: 68

## icons
- library: tabler-outline
- stroke_width: 2
- inventory: tabler-outline/shield-lock, tabler-outline/network, tabler-outline/database, tabler-outline/chart-line, tabler-outline/microscope, tabler-outline/alert-triangle, tabler-outline/check, tabler-outline/clock, tabler-outline/arrows-split, tabler-outline/brain

## images
- paper-architecture: images/NetworkData2_p3_2.jpeg | source=user | crop=no-crop
- paper-capture-setup: images/NetworkData2_p5_5.jpeg | source=user | crop=no-crop

## page_visualizations
- P07: chart/grouped_bar_chart
- P08: chart/line_chart
- P10: chart/grouped_bar_chart
- P12: table/comparison_matrix
- P13: chart/grouped_bar_chart

## page_rhythm
- P01: anchor
- P02: breathing
- P03: dense
- P04: dense
- P05: dense
- P06: dense
- P07: dense
- P08: dense
- P09: dense
- P10: dense
- P11: breathing
- P12: dense
- P13: anchor
- P14: dense
- P15: anchor

## pptx_structure
- mode: flat

## forbidden
- `mask`, `<style>`, `class`, external CSS, `<foreignObject>`, `textPath`, `@font-face`, `<animate*>`, `<set>`, `<script>` / event attributes, `<iframe>`
- HTML named entities in text; write typography as raw Unicode and escape XML reserved characters
