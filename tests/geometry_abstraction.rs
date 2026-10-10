use filang::{
    geometry::{pair_catalogue, BodyDirection, Boundary, GeometryMode, GeometryPattern},
    geometry_abstraction::{
        partition_input, Endpoint, EndpointPair, ExactFactorization, Schema,
        MAX_ABSTRACTION_ENDPOINTS,
    },
};
use std::collections::{BTreeMap, HashSet};

fn ep(bar: usize, boundary: Boundary) -> Endpoint {
    Endpoint::new(bar, boundary)
}

fn pair(a: Endpoint, b: Endpoint) -> EndpointPair {
    EndpointPair::new(a, b).unwrap()
}

fn literal(text: &str) -> GeometryPattern {
    text.parse().unwrap()
}

#[test]
fn signature_is_canonical_portable_and_keeps_its_own_schema() {
    let ab = pair(ep(0, Boundary::High), ep(1, Boundary::Low));
    let bc = pair(ep(0, Boundary::BodyHigh), ep(1, Boundary::BodyLow));
    assert_eq!(pair(ep(1, Boundary::Low), ep(0, Boundary::High)), ab);
    assert!(EndpointPair::new(ep(0, Boundary::Low), ep(0, Boundary::Low)).is_err());
    let s1 = Schema::new(2, GeometryMode::Oriented, vec![ab, bc, ab], vec![1, 0, 1]).unwrap();
    let s2 = Schema::new(2, GeometryMode::Oriented, vec![bc, ab], vec![0, 1]).unwrap();
    assert_eq!(s1, s2);
    assert_eq!(s1.comparisons().len(), 2);
    let g = literal("g1:o:0,1,2,3,u;4,5,6,7,d");
    let sig = s1.signature(&g).unwrap();
    assert!(sig.matches(&g).unwrap());
    assert_eq!(sig.direction(0), Some(BodyDirection::Up));
    assert_eq!(sig.direction(1), Some(BodyDirection::Down));
    assert_eq!(sig.relation(ab), Some(std::cmp::Ordering::Less));
    assert_eq!(sig.relation(bc), Some(std::cmp::Ordering::Less));
    assert_eq!(
        sig.relation(pair(ep(0, Boundary::Low), ep(1, Boundary::High))),
        None
    );
    assert_eq!(s1.signature(&g).unwrap(), s2.signature(&g).unwrap());

    // Full signature comparisons must include *schema identity*, so equal
    // answer vectors under different questions can never alias.
    let different = Schema::new(2, GeometryMode::Oriented, vec![bc], vec![0, 1]).unwrap();
    assert_ne!(sig, different.signature(&g).unwrap());
    assert!(Schema::empty(1, GeometryMode::Oriented)
        .unwrap()
        .signature(&g)
        .is_err());
    assert!(Schema::empty(2, GeometryMode::Unoriented)
        .unwrap()
        .signature(&g)
        .is_err());
}

#[test]
fn refinement_has_an_exact_forgetful_law() {
    let p = pair(ep(0, Boundary::Low), ep(1, Boundary::BodyLow));
    let q = pair(ep(0, Boundary::High), ep(1, Boundary::High));
    let coarse = Schema::empty(2, GeometryMode::Oriented)
        .unwrap()
        .with_comparison(p)
        .unwrap();
    let fine = coarse
        .with_comparison(q)
        .unwrap()
        .with_direction(1)
        .unwrap();
    assert!(fine.is_refinement_of(&coarse));
    assert!(!coarse.is_refinement_of(&fine));
    let g = literal("g1:o:0,1,3,4,u;0,2,3,5,d");
    assert_eq!(
        coarse.coarsen(&fine.signature(&g).unwrap()).unwrap(),
        coarse.signature(&g).unwrap()
    );
    assert!(fine.coarsen(&coarse.signature(&g).unwrap()).is_err());
    let wrong = Schema::empty(2, GeometryMode::Unoriented).unwrap();
    assert!(!coarse.is_refinement_of(&wrong));
    assert!(wrong.coarsen(&fine.signature(&g).unwrap()).is_err());
}

#[test]
fn nonadjacent_information_is_collapsed_by_local_descriptions_but_exactly_recoverable() {
    let a = GeometryPattern::from_endpoints(
        &[
            [10., 11., 12., 13.],
            [20., 21., 22., 23.],
            [14., 15., 16., 17.],
        ],
        GeometryMode::Unoriented,
        None,
    )
    .unwrap();
    let b = GeometryPattern::from_endpoints(
        &[[10., 11., 12., 13.], [20., 21., 22., 23.], [6., 7., 8., 9.]],
        GeometryMode::Unoriented,
        None,
    )
    .unwrap();
    assert_ne!(a, b);
    // Select every comparison within the adjacent AB and BC windows, but
    // none of the comparisons between the nonadjacent A and C candles.
    let mut pairs = Vec::new();
    let endpoints = [
        Boundary::Low,
        Boundary::BodyLow,
        Boundary::BodyHigh,
        Boundary::High,
    ];
    for (i, j) in [(0, 1), (1, 2)] {
        for &left in &endpoints {
            for &right in &endpoints {
                pairs.push(pair(ep(i, left), ep(j, right)));
            }
        }
    }
    let schema = Schema::new(3, GeometryMode::Unoriented, pairs, vec![]).unwrap();
    let sa = schema.signature(&a).unwrap();
    let sb = schema.signature(&b).unwrap();
    assert_eq!(sa, sb);
    assert!(sa.matches(&b).unwrap());
    let groups = partition_input(&schema, &[a.clone(), b.clone()]).unwrap();
    assert_eq!(groups.len(), 1);
    assert_eq!(groups[0].indices(), &[0, 1]);
    for source in [a, b] {
        let parts = ExactFactorization::from_pattern(&schema, &source).unwrap();
        assert_eq!(parts.signature(), &sa);
        assert_eq!(parts.reconstruct().unwrap(), source);
        assert!(parts.residual().comparisons().len() < 4 * 3);
    }
}

#[test]
fn exact_factorization_reconstructs_all_two_candle_legal_geometries() {
    for mode in [GeometryMode::Unoriented, GeometryMode::Oriented] {
        let patterns = pair_catalogue(mode).unwrap();
        assert_eq!(
            patterns.len(),
            if mode == GeometryMode::Oriented {
                7452
            } else {
                2568
            }
        );
        let empty = Schema::empty(2, mode).unwrap();
        let complete = Schema::complete(2, mode).unwrap();
        // A middle basis chooses a few nontrivial structural features and,
        // when oriented, just one direction.
        let middle = Schema::new(
            2,
            mode,
            vec![
                pair(ep(0, Boundary::Low), ep(1, Boundary::High)),
                pair(ep(0, Boundary::BodyHigh), ep(1, Boundary::BodyLow)),
            ],
            if mode == GeometryMode::Oriented {
                vec![0]
            } else {
                vec![]
            },
        )
        .unwrap();

        for pattern in &patterns {
            for schema in [&empty, &middle, &complete] {
                let factor = ExactFactorization::from_pattern(schema, pattern).unwrap();
                assert_eq!(factor.reconstruct().unwrap(), *pattern);
                assert!(factor.signature().matches(pattern).unwrap());
                assert!(factor.residual().comparisons().len() <= 7);
            }
            let full = ExactFactorization::from_pattern(&complete, pattern).unwrap();
            assert!(full.residual().comparisons().is_empty());
            assert!(full.residual().directions().is_empty());
        }

        // Exact quotient of the *enumerated legal two-candle universe*.
        let full_groups = partition_input(&complete, &patterns).unwrap();
        assert_eq!(full_groups.len(), patterns.len());
        assert!(full_groups.iter().all(|group| group.len() == 1));
        let middle_groups = partition_input(&middle, &patterns).unwrap();
        assert!(middle_groups.len() > 1);
        assert!(middle_groups.len() < full_groups.len());
        let empty_groups = partition_input(&empty, &patterns).unwrap();
        assert_eq!(empty_groups.len(), 1);
        assert_eq!(empty_groups[0].len(), patterns.len());
        assert_eq!(
            middle_groups.iter().map(|group| group.len()).sum::<usize>(),
            patterns.len()
        );
        // Every finer class belongs to exactly one coarser class. This is a
        // computed partition law on all legal two-candle states, not a
        // market information or speedup claim.
        let mid_membership: BTreeMap<_, _> = middle_groups
            .iter()
            .flat_map(|g| g.indices().iter().map(move |&i| (i, g.signature().clone())))
            .collect();
        let mut coarse_membership = BTreeMap::new();
        for g in empty_groups {
            for &index in g.indices() {
                coarse_membership.insert(index, g.signature().clone());
            }
        }
        for (index, sig) in mid_membership {
            assert_eq!(empty.coarsen(&sig).unwrap(), coarse_membership[&index]);
        }
    }
}

#[test]
fn orientation_can_be_refined_without_changing_any_endpoint_relation() {
    let ranks = vec![[0, 1, 2, 3], [4, 5, 6, 7]];
    let a = GeometryPattern::new(
        ranks.clone(),
        Some(vec![BodyDirection::Up, BodyDirection::Down]),
    )
    .unwrap();
    let b =
        GeometryPattern::new(ranks, Some(vec![BodyDirection::Down, BodyDirection::Down])).unwrap();
    let pure_shape = Schema::new(
        2,
        GeometryMode::Oriented,
        vec![pair(ep(0, Boundary::High), ep(1, Boundary::Low))],
        vec![],
    )
    .unwrap();
    let oriented = pure_shape.with_direction(0).unwrap();
    assert_eq!(
        pure_shape.signature(&a).unwrap(),
        pure_shape.signature(&b).unwrap()
    );
    assert_ne!(
        oriented.signature(&a).unwrap(),
        oriented.signature(&b).unwrap()
    );
    assert_eq!(
        pure_shape
            .coarsen(&oriented.signature(&a).unwrap())
            .unwrap(),
        pure_shape.signature(&a).unwrap()
    );
    for (schema, g) in [(&pure_shape, &a), (&oriented, &b)] {
        assert_eq!(
            ExactFactorization::from_pattern(schema, g)
                .unwrap()
                .reconstruct()
                .unwrap(),
            *g
        );
    }
}

#[test]
fn input_partition_counts_occurrences_not_unobserved_legal_cardinality() {
    let a = literal("g1:u:0,0,0,0;1,1,1,1");
    let b = literal("g1:u:1,1,1,1;0,0,0,0");
    let schema = Schema::empty(2, GeometryMode::Unoriented).unwrap();
    let groups = partition_input(&schema, &[a.clone(), a.clone(), b.clone()]).unwrap();
    assert_eq!(groups.len(), 1);
    assert_eq!(groups[0].indices(), &[0, 1, 2]);
    let precise = schema
        .with_comparison(pair(ep(0, Boundary::Low), ep(1, Boundary::Low)))
        .unwrap();
    let groups = partition_input(&precise, &[a, b]).unwrap();
    assert_eq!(groups.len(), 2);
    assert_eq!(
        groups
            .iter()
            .map(|group| group.indices().len())
            .sum::<usize>(),
        2
    );
}

#[test]
fn phase_one_projection_and_phase_two_lift_commute_exactly() {
    let full = literal("g1:o:0,1,2,3,u;1,2,3,4,d;3,4,5,6,u;0,0,1,7,d");
    let basis = Schema::new(
        2,
        GeometryMode::Oriented,
        vec![
            pair(ep(0, Boundary::BodyHigh), ep(1, Boundary::Low)),
            pair(ep(0, Boundary::High), ep(1, Boundary::High)),
        ],
        vec![0, 1],
    )
    .unwrap();
    let indices = [0, 3];
    let projected = filang::geometry_algebra::project(&full, &indices).unwrap();
    let projected_signature = basis.signature_on_projection(&full, &indices).unwrap();
    assert_eq!(projected_signature, basis.signature(&projected).unwrap());
    let lifted = basis.lift_to(full.len(), &indices).unwrap();
    let lifted_signature = lifted.signature(&full).unwrap();
    assert_eq!(
        projected_signature.relations(),
        lifted_signature.relations()
    );
    assert_eq!(
        projected_signature.directions(),
        lifted_signature.directions()
    );
    assert_ne!(projected_signature, lifted_signature);
    assert_eq!(lifted.comparisons()[0].first().candle, 0);
    assert_eq!(lifted.comparisons()[0].second().candle, 3);
    assert!(basis.lift_to(4, &[3, 0]).is_err());
    assert!(basis.lift_to(4, &[0, 0]).is_err());
    assert!(basis.lift_to(4, &[0, 4]).is_err());
    assert!(basis.lift_to(4, &[0]).is_err());
    assert!(basis.signature_on_projection(&full, &[0, 4]).is_err());
}

#[test]
fn schemas_form_a_distributive_selection_lattice_without_semantic_guessing() {
    let x = pair(ep(0, Boundary::Low), ep(1, Boundary::High));
    let y = pair(ep(0, Boundary::BodyLow), ep(1, Boundary::BodyHigh));
    let z = pair(ep(0, Boundary::High), ep(1, Boundary::Low));
    let empty = Schema::empty(2, GeometryMode::Oriented).unwrap();
    let top = Schema::complete(2, GeometryMode::Oriented).unwrap();
    let a = empty.with_comparison(x).unwrap().with_direction(0).unwrap();
    let b = empty.with_comparison(y).unwrap().with_direction(0).unwrap();
    let c = empty.with_comparison(z).unwrap().with_direction(1).unwrap();

    assert!(a.join(&b).unwrap().is_refinement_of(&a));
    assert!(a.join(&b).unwrap().is_refinement_of(&b));
    assert!(a.is_refinement_of(&a.meet(&b).unwrap()));
    assert!(b.is_refinement_of(&a.meet(&b).unwrap()));
    assert_eq!(a.join(&a).unwrap(), a);
    assert_eq!(a.meet(&a).unwrap(), a);
    assert_eq!(a.join(&empty).unwrap(), a);
    assert_eq!(a.meet(&top).unwrap(), a);
    assert_eq!(a.meet(&b).unwrap().join(&a).unwrap(), a);
    assert_eq!(a.join(&b).unwrap().meet(&a).unwrap(), a);
    assert_eq!(
        a.meet(&b.join(&c).unwrap()).unwrap(),
        a.meet(&b).unwrap().join(&a.meet(&c).unwrap()).unwrap()
    );
    assert_eq!(
        a.join(&b.meet(&c).unwrap()).unwrap(),
        a.join(&b).unwrap().meet(&a.join(&c).unwrap()).unwrap()
    );
    assert!(a
        .join(&Schema::empty(3, GeometryMode::Oriented).unwrap())
        .is_err());
    assert!(a
        .meet(&Schema::empty(2, GeometryMode::Unoriented).unwrap())
        .is_err());
}

#[test]
fn invalid_and_empty_inputs_have_explicit_boundaries() {
    let invalid = pair(ep(0, Boundary::Low), ep(2, Boundary::High));
    assert!(Schema::new(2, GeometryMode::Unoriented, vec![invalid], vec![]).is_err());
    assert!(Schema::new(2, GeometryMode::Unoriented, vec![], vec![0]).is_err());
    assert!(Schema::new(2, GeometryMode::Oriented, vec![], vec![2]).is_err());
    assert!(Schema::empty(MAX_ABSTRACTION_ENDPOINTS / 4 + 1, GeometryMode::Oriented).is_err());
    assert!(Schema::empty(usize::MAX, GeometryMode::Unoriented).is_err());

    let empty = Schema::empty(0, GeometryMode::Oriented).unwrap();
    let p = literal("g1:o:");
    let factor = ExactFactorization::from_pattern(&empty, &p).unwrap();
    assert_eq!(factor.reconstruct().unwrap(), p);
    assert!(factor.residual().comparisons().is_empty());
    let groups = partition_input(&empty, &[]).unwrap();
    assert!(groups.is_empty());
    assert!(empty.with_direction(0).is_err());
    assert!(empty
        .with_comparison(pair(ep(0, Boundary::Low), ep(1, Boundary::High)))
        .is_err());
}

fn next(seed: &mut u64) -> u32 {
    *seed ^= *seed << 13;
    *seed ^= *seed >> 7;
    *seed ^= *seed << 17;
    (*seed >> 16) as u32
}

#[test]
fn random_qualitative_ties_gaps_wicks_and_modes_preserve_exact_laws() {
    let mut seed = 0x1643_2026_a11d_0001u64;
    let cmp = pair(ep(0, Boundary::High), ep(3, Boundary::Low));
    for mode in [GeometryMode::Unoriented, GeometryMode::Oriented] {
        let coarse = Schema::empty(4, mode)
            .unwrap()
            .with_comparison(cmp)
            .unwrap();
        let refined = coarse
            .with_comparison(pair(ep(0, Boundary::BodyLow), ep(2, Boundary::BodyHigh)))
            .unwrap();
        let refined = if mode == GeometryMode::Oriented {
            refined.with_direction(1).unwrap()
        } else {
            refined
        };
        for _ in 0..1500 {
            let rows: Vec<_> = (0..4)
                .map(|_| {
                    let open = (next(&mut seed) % 13) as f64;
                    let close = (next(&mut seed) % 13) as f64;
                    let low = open.min(close) - (next(&mut seed) % 2) as f64;
                    let high = open.max(close) + (next(&mut seed) % 2) as f64;
                    [open, high, low, close]
                })
                .collect();
            let g = GeometryPattern::from_ohlc(&rows, mode).unwrap();
            let fine = refined.signature(&g).unwrap();
            assert_eq!(
                coarse.coarsen(&fine).unwrap(),
                coarse.signature(&g).unwrap()
            );
            let factor = ExactFactorization::from_pattern(&refined, &g).unwrap();
            assert_eq!(factor.reconstruct().unwrap(), g);
            assert!(fine.matches(&g).unwrap());
            assert!(factor.residual().comparisons().len() <= 15);
        }
    }
}

#[test]
fn fully_selected_comparison_signatures_are_collision_free_for_sampled_patterns() {
    let patterns = pair_catalogue(GeometryMode::Unoriented).unwrap();
    let schema = Schema::complete(2, GeometryMode::Unoriented).unwrap();
    let sigs: HashSet<_> = patterns
        .iter()
        .map(|p| schema.signature(p).unwrap())
        .collect();
    assert_eq!(sigs.len(), patterns.len());
}
